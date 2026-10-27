"""Tests for GitHub workflow_run webhook failure prediction."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes import webhooks
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models.models import Execution, RepositoryInstallation, WorkflowFailure


TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = async_sessionmaker(test_engine, expire_on_commit=False)


def _build_webhook_app() -> FastAPI:
    test_app = FastAPI(title="Webhook Test App")
    test_app.include_router(webhooks.router, prefix="/api/v1/webhooks")
    return test_app


app = _build_webhook_app()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture()
async def db_session() -> AsyncSession:
    async with TestSession() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(autouse=True)
async def override_db(db_session: AsyncSession):
    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def allow_unsigned_webhook_tests(monkeypatch):
    monkeypatch.setattr(webhooks, "verify_webhook_signature", lambda payload, signature: True)


def _failed_workflow_payload() -> dict:
    return {
        "action": "completed",
        "repository": {"full_name": "octo-org/demo-app"},
        "workflow_run": {
            "id": 123456789,
            "name": "CI",
            "conclusion": "failure",
            "head_branch": "feature/demo",
            "html_url": "https://github.com/octo-org/demo-app/actions/runs/123456789",
        },
    }


def _auth_headers(role: str = "admin") -> dict[str, str]:
    token = create_access_token(
        {
            "sub": str(uuid.uuid4()),
            "username": "webhook-debug-test-user",
            "role": role,
        }
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_failed_workflow_run_predicts_and_creates_execution(
    client: TestClient,
    db_session: AsyncSession,
    monkeypatch,
):
    calls: list[str] = []

    def _fake_predict_failure(log_text: str) -> dict:
        calls.append(log_text)
        return {
            "label": "npm_missing_test_script",
            "confidence": 0.82,
            "suggested_fix": "Add a test script in package.json.",
            "recommendation": {
                "summary": "The CI job ran npm test, but package.json does not define a test script.",
                "root_cause": "The Node.js workflow expects scripts.test to exist.",
                "safe_fix_available": True,
                "recommended_changes": ["Add scripts.test to package.json."],
                "risk_level": "low",
                "requires_approval": False,
            },
        }

    def _fake_download_workflow_logs(repo_full_name: str, run_id: int) -> str:
        assert repo_full_name == "octo-org/demo-app"
        assert run_id == 123456789
        return "downloaded GitHub Actions log: npm ERR! Missing script: test"

    monkeypatch.setattr(webhooks, "download_workflow_logs", _fake_download_workflow_logs)
    monkeypatch.setattr(webhooks.failure_prediction_service, "predict_failure", _fake_predict_failure)

    response = client.post(
        "/api/v1/webhooks/github",
        headers={"X-GitHub-Event": "workflow_run"},
        json=_failed_workflow_payload(),
    )

    assert response.status_code == 200
    assert response.json() == {"received": True, "event": "workflow_run"}
    assert calls == ["downloaded GitHub Actions log: npm ERR! Missing script: test"]

    result = await db_session.execute(select(Execution).where(Execution.source == "webhook"))
    execution = result.scalar_one()
    assert execution.status == "completed"
    assert execution.requested_by == "github_webhook"
    assert execution.tool_name == "failure_prediction_model"
    assert "npm_missing_test_script" in execution.summary

    details = json.loads(execution.details or "{}")
    assert details["repo"] == "octo-org/demo-app"
    assert details["workflow_run_id"] == 123456789
    assert details["workflow"] == "CI"
    assert details["branch"] == "feature/demo"
    assert details["html_url"] == "https://github.com/octo-org/demo-app/actions/runs/123456789"
    assert details["log_source"] == "github_actions"
    assert details["log_chars"] == 60
    assert details["log_excerpt"] == "downloaded GitHub Actions log: npm ERR! Missing script: test"
    assert details["predicted_label"] == "npm_missing_test_script"
    assert details["confidence"] == 0.82
    assert details["suggested_fix"] == "Add a test script in package.json."
    assert details["recommendation"]["risk_level"] == "low"
    assert details["prediction"]["label"] == "npm_missing_test_script"

    failure_result = await db_session.execute(select(WorkflowFailure))
    failure = failure_result.scalar_one()
    assert failure.repo_full_name == "octo-org/demo-app"
    assert failure.workflow_run_id == 123456789
    assert failure.workflow_name == "CI"
    assert failure.branch == "feature/demo"
    assert failure.conclusion == "failure"
    assert failure.workflow_url == "https://github.com/octo-org/demo-app/actions/runs/123456789"
    assert failure.log_excerpt == "downloaded GitHub Actions log: npm ERR! Missing script: test"
    assert failure.predicted_label == "npm_missing_test_script"
    assert failure.confidence == 0.82
    assert failure.suggested_fix == "Add a test script in package.json."
    assert failure.recommendation is not None
    assert failure.recommendation["safe_fix_available"] is True
    assert failure.fix_pr_url is None
    assert failure.status == "diagnosed"


@pytest.mark.asyncio
async def test_failed_workflow_run_uses_installation_token(
    client: TestClient,
    monkeypatch,
):
    payload = _failed_workflow_payload()
    payload["installation"] = {"id": 99}

    monkeypatch.setattr(webhooks, "get_installation_access_token", lambda installation_id: "installation-token")
    monkeypatch.setattr(
        webhooks.failure_prediction_service,
        "predict_failure",
        lambda log_text: {
            "label": "unknown_failure",
            "confidence": 0.4,
            "suggested_fix": "Review logs.",
            "recommendation": {"risk_level": "medium", "requires_approval": False},
        },
    )

    def _fake_download_workflow_logs(repo_full_name: str, run_id: int, *, token: str | None = None) -> str:
        assert token == "installation-token"
        return "downloaded log from installation token"

    monkeypatch.setattr(webhooks, "download_workflow_logs", _fake_download_workflow_logs)

    response = client.post(
        "/api/v1/webhooks/github",
        headers={"X-GitHub-Event": "workflow_run"},
        json=payload,
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_installation_webhook_stores_installed_repositories(
    client: TestClient,
    db_session: AsyncSession,
):
    response = client.post(
        "/api/v1/webhooks/github",
        headers={"X-GitHub-Event": "installation"},
        json={
            "action": "created",
            "installation": {"id": 987},
            "repositories": [
                {"full_name": "octo-org/demo-app", "default_branch": "main"},
                {"full_name": "octo-org/api", "default_branch": "develop"},
            ],
        },
    )

    assert response.status_code == 200
    result = await db_session.execute(select(RepositoryInstallation).order_by(RepositoryInstallation.repo_full_name))
    records = result.scalars().all()
    assert [record.repo_full_name for record in records] == ["octo-org/api", "octo-org/demo-app"]
    assert {record.installation_id for record in records} == {987}
    assert all(record.status == "active" for record in records)


@pytest.mark.asyncio
async def test_installation_repositories_webhook_marks_removed_repository(
    client: TestClient,
    db_session: AsyncSession,
):
    response = client.post(
        "/api/v1/webhooks/github",
        headers={"X-GitHub-Event": "installation_repositories"},
        json={
            "action": "removed",
            "installation": {"id": 987},
            "repositories_added": [],
            "repositories_removed": [
                {"full_name": "octo-org/demo-app", "default_branch": "main"},
            ],
        },
    )

    assert response.status_code == 200
    result = await db_session.execute(select(RepositoryInstallation))
    record = result.scalar_one()
    assert record.repo_full_name == "octo-org/demo-app"
    assert record.status == "removed"


@pytest.mark.asyncio
async def test_successful_workflow_run_does_not_predict(
    client: TestClient,
    db_session: AsyncSession,
    monkeypatch,
):
    def _unexpected_predict_failure(log_text: str) -> dict:
        raise AssertionError(f"predict_failure should not be called for: {log_text}")

    payload = _failed_workflow_payload()
    payload["workflow_run"]["conclusion"] = "success"
    monkeypatch.setattr(webhooks.failure_prediction_service, "predict_failure", _unexpected_predict_failure)

    response = client.post(
        "/api/v1/webhooks/github",
        headers={"X-GitHub-Event": "workflow_run"},
        json=payload,
    )

    assert response.status_code == 200
    result = await db_session.execute(select(Execution).where(Execution.source == "webhook"))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_failed_workflow_run_returns_200_when_diagnosis_crashes(
    client: TestClient,
    db_session: AsyncSession,
    monkeypatch,
):
    def _broken_download_workflow_logs(repo_full_name: str, run_id: int) -> str:
        raise ValueError("internal stack trace should not be exposed")

    monkeypatch.setattr(webhooks, "download_workflow_logs", _broken_download_workflow_logs)

    response = client.post(
        "/api/v1/webhooks/github",
        headers={"X-GitHub-Event": "workflow_run"},
        json=_failed_workflow_payload(),
    )

    assert response.status_code == 200
    assert response.json() == {"received": True, "event": "workflow_run"}

    result = await db_session.execute(select(Execution).where(Execution.source == "webhook"))
    execution = result.scalar_one()
    assert execution.status == "failed"
    assert "internal stack trace" not in execution.summary
    details = json.loads(execution.details or "{}")
    assert details["error"] == "Unexpected webhook failure diagnosis error."

    failure_result = await db_session.execute(select(WorkflowFailure))
    failure = failure_result.scalar_one()
    assert failure.status == "diagnosis_failed"
    assert failure.predicted_label is None


@pytest.mark.asyncio
async def test_failed_workflow_run_returns_200_when_prediction_fails(
    client: TestClient,
    db_session: AsyncSession,
    monkeypatch,
):
    def _fake_download_workflow_logs(repo_full_name: str, run_id: int) -> str:
        return "downloaded GitHub Actions log: pytest assertion failed"

    def _broken_predict_failure(log_text: str) -> dict:
        raise webhooks.FailurePredictionError("model could not classify this log")

    monkeypatch.setattr(webhooks, "download_workflow_logs", _fake_download_workflow_logs)
    monkeypatch.setattr(webhooks.failure_prediction_service, "predict_failure", _broken_predict_failure)

    response = client.post(
        "/api/v1/webhooks/github",
        headers={
            "X-GitHub-Event": "workflow_run",
            "X-GitHub-Delivery": "delivery-123",
        },
        json=_failed_workflow_payload(),
    )

    assert response.status_code == 200
    assert response.json() == {"received": True, "event": "workflow_run"}

    result = await db_session.execute(select(Execution).where(Execution.source == "webhook"))
    execution = result.scalar_one()
    assert execution.status == "failed"
    details = json.loads(execution.details or "{}")
    assert details["request_id"] == "delivery-123"
    assert details["error"] == "model could not classify this log"

    failure_result = await db_session.execute(select(WorkflowFailure))
    failure = failure_result.scalar_one()
    assert failure.status == "diagnosis_failed"
    assert failure.log_excerpt == "downloaded GitHub Actions log: pytest assertion failed"


@pytest.mark.asyncio
async def test_recent_webhook_events_returns_webhook_audit_records(
    client: TestClient,
    db_session: AsyncSession,
):
    execution = Execution(
        id=str(uuid.uuid4()),
        requested_by="github_webhook",
        tool_name="failure_prediction_model",
        tool_input="{}",
        status="failed",
        summary="Webhook diagnosis failed for octo-org/demo-app",
        details=json.dumps({"request_id": "debug-request-id"}),
        source="webhook",
        started_at=datetime.now(tz=timezone.utc),
        completed_at=datetime.now(tz=timezone.utc),
    )
    db_session.add(execution)
    await db_session.flush()

    response = client.get("/api/v1/webhooks/recent-events", headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == execution.id
    assert body[0]["source"] == "webhook"
    assert body[0]["tool_name"] == "failure_prediction_model"
