"""Tests for workflow failure diagnosis persistence and API routes."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes import workflow_failures
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models.models import ApprovalRequest
from app.services.workflow_failure_service import create_workflow_failure, list_workflow_failures


TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = async_sessionmaker(test_engine, expire_on_commit=False)


def _build_test_app() -> FastAPI:
    test_app = FastAPI(title="Workflow Failure Test App")
    test_app.include_router(workflow_failures.router, prefix="/api/v1/workflow-failures")
    return test_app


app = _build_test_app()


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


def _auth_headers(role: str = "developer", username: str = "workflow-failure-test-user") -> dict[str, str]:
    token = create_access_token(
        {
            "sub": str(uuid.uuid4()),
            "username": username,
            "role": role,
        }
    )
    return {"Authorization": f"Bearer {token}"}


async def _create_failure(db_session: AsyncSession):
    return await create_workflow_failure(
        db_session,
        repo_full_name="octo-org/demo-app",
        requested_by="workflow-failure-test-user",
        workflow_run_id=123456789,
        workflow_name="CI",
        branch="feature/demo",
        conclusion="failure",
        workflow_url="https://github.com/octo-org/demo-app/actions/runs/123456789",
        log_excerpt="npm ERR! Missing script: test",
        predicted_label="npm_missing_test_script",
        confidence=0.82,
        suggested_fix="Add a test script to package.json.",
        recommendation={
            "summary": "The CI job ran npm test, but package.json does not define a test script.",
            "root_cause": "Missing scripts.test.",
            "safe_fix_available": True,
            "recommended_changes": ["Add scripts.test to package.json."],
            "risk_level": "low",
            "requires_approval": False,
        },
        status="diagnosed",
    )


@pytest.mark.asyncio
async def test_create_and_list_workflow_failures_service(db_session: AsyncSession):
    record = await _create_failure(db_session)

    records = await list_workflow_failures(db_session)

    assert len(records) == 1
    assert records[0].id == record.id
    assert records[0].repo_full_name == "octo-org/demo-app"
    assert records[0].predicted_label == "npm_missing_test_script"


@pytest.mark.asyncio
async def test_list_workflow_failures_endpoint(client: TestClient, db_session: AsyncSession):
    record = await _create_failure(db_session)

    response = client.get("/api/v1/workflow-failures", headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == record.id
    assert body[0]["repo_full_name"] == "octo-org/demo-app"
    assert body[0]["workflow_run_id"] == 123456789
    assert body[0]["workflow_name"] == "CI"
    assert body[0]["branch"] == "feature/demo"
    assert body[0]["conclusion"] == "failure"
    assert body[0]["predicted_label"] == "npm_missing_test_script"
    assert body[0]["confidence"] == 0.82
    assert body[0]["recommendation"]["risk_level"] == "low"
    assert body[0]["fix_pr_url"] is None
    assert body[0]["status"] == "diagnosed"


@pytest.mark.asyncio
async def test_get_workflow_failure_endpoint(client: TestClient, db_session: AsyncSession):
    record = await _create_failure(db_session)

    response = client.get(f"/api/v1/workflow-failures/{record.id}", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["id"] == record.id


@pytest.mark.asyncio
async def test_create_fix_pr_endpoint_hides_another_developers_failure(client: TestClient, db_session: AsyncSession):
    record = await _create_failure(db_session)

    response = client.post(
        f"/api/v1/workflow-failures/{record.id}/create-fix-pr",
        headers=_auth_headers("developer", "other-developer"),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_fix_pr_endpoint_returns_service_result(monkeypatch, client: TestClient, db_session: AsyncSession):
    record = await _create_failure(db_session)

    async def _fake_create_fix_pr_for_failure(db, failure_id, current_user):
        assert failure_id == record.id
        assert current_user["role"] == "admin"
        return {
            "workflow_failure_id": record.id,
            "repo_full_name": "octo-org/demo-app",
            "status": "fix_pr_created",
            "branch": "ai-cicd/fix-123456789",
            "workflow_path": ".github/workflows/ci.yml",
            "pull_request_url": "https://github.com/octo-org/demo-app/pull/22",
            "message": "Changed npm test to npm test --if-present in the workflow.",
            "recommendation": record.recommendation,
        }

    monkeypatch.setattr(workflow_failures, "create_fix_pr_for_failure", _fake_create_fix_pr_for_failure)

    response = client.post(f"/api/v1/workflow-failures/{record.id}/create-fix-pr", headers=_auth_headers("admin"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "fix_pr_created"
    assert body["branch"] == "ai-cicd/fix-123456789"
    assert body["pull_request_url"] == "https://github.com/octo-org/demo-app/pull/22"


@pytest.mark.asyncio
async def test_create_fix_pr_endpoint_creates_approval_for_medium_risk(
    client: TestClient,
    db_session: AsyncSession,
):
    record = await create_workflow_failure(
        db_session,
        repo_full_name="octo-org/demo-app",
        workflow_run_id=4321,
        workflow_name="CI",
        conclusion="failure",
        predicted_label="wrong_runtime_version",
        suggested_fix="Update the workflow runtime version.",
        recommendation={
            "summary": "Runtime version mismatch.",
            "root_cause": "CI selected an incompatible runtime.",
            "safe_fix_available": True,
            "recommended_changes": ["Update setup-node or setup-python to the required version."],
            "risk_level": "medium",
            "requires_approval": True,
        },
        status="diagnosed",
    )

    response = client.post(f"/api/v1/workflow-failures/{record.id}/create-fix-pr", headers=_auth_headers("admin"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approval_required"
    assert body["approval_id"]
    assert body["approval_details"]["repository"] == "octo-org/demo-app"
    assert body["approval_details"]["workflow_run_id"] == 4321
    assert body["approval_details"]["risk_level"] == "medium"
    await db_session.refresh(record)
    assert record.status == "approval_pending"

    approval_result = await db_session.execute(select(ApprovalRequest).where(ApprovalRequest.id == body["approval_id"]))
    approval = approval_result.scalar_one()
    assert approval.status == "pending"
    assert approval.tool_name == "github_create_fix_pr"


def test_workflow_failures_endpoint_requires_auth(client: TestClient):
    response = client.get("/api/v1/workflow-failures")

    assert response.status_code in (401, 403)


def test_get_workflow_failure_endpoint_returns_404(client: TestClient):
    response = client.get(f"/api/v1/workflow-failures/{uuid.uuid4()}", headers=_auth_headers())

    assert response.status_code == 404


def _run(run_id=1234):
    return {"id": run_id, "name": "CI", "head_branch": "main", "conclusion": "failure"}


@pytest.mark.asyncio
async def test_sync_imports_real_metadata_without_logs_and_deduplicates(monkeypatch, client, db_session):
    from app.core.config import settings
    from app.tools import github_tool
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "")
    monkeypatch.setattr(github_tool, "list_failed_workflow_runs", lambda *args, **kwargs: [_run()])
    first = client.post("/api/v1/workflow-failures/sync", headers=_auth_headers(),
                        json={"repo_full_name": "octo-org/demo-app"})
    assert first.status_code == 200
    item = first.json()["failures"][0]
    assert first.json()["imported"] == 1 and item["workflow_run_id"] == 1234
    assert item["requested_by"] == "workflow-failure-test-user"
    assert item["status"] == "logs_unavailable" and "Paste" in item["diagnosis_error"]
    second = client.post("/api/v1/workflow-failures/sync", headers=_auth_headers(),
                         json={"repo_full_name": "octo-org/demo-app"})
    assert second.json()["imported"] == 0 and second.json()["failures"][0]["id"] == item["id"]
    assert len(client.get("/api/v1/workflow-failures", headers=_auth_headers()).json()) == 1


@pytest.mark.asyncio
async def test_imported_logs_are_diagnosed_redacted_and_owned(monkeypatch, client, db_session):
    from app.services import failure_prediction_service
    captured = []

    def predict(log):
        captured.append(log)
        return {"label": "npm_missing_test_script", "confidence": 0.93, "suggested_fix": "Add a test script."}
    monkeypatch.setattr(failure_prediction_service, "predict_failure", predict)
    payload = {"repo_full_name": "octo-org/demo-app", "workflow_run_id": 100,
               "log_text": "npm ERR! Missing script: test\ntoken ghp_" + "a" * 30}
    response = client.post("/api/v1/workflow-failures/import", json=payload, headers=_auth_headers())
    assert response.status_code == 200
    item = response.json()
    assert item["status"] == "diagnosed" and item["predicted_label"] == "npm_missing_test_script"
    assert "a" * 30 not in item["log_excerpt"] and "a" * 30 not in captured[0]
    assert client.get(f"/api/v1/workflow-failures/{item['id']}",
                      headers=_auth_headers(username="another-developer")).status_code == 404
    assert client.get("/api/v1/workflow-failures", headers=_auth_headers(username="another-developer")).json() == []
    assert len(client.get("/api/v1/workflow-failures", headers=_auth_headers("admin")).json()) == 1
    second = client.post("/api/v1/workflow-failures/import", json=payload, headers=_auth_headers())
    assert second.json()["id"] == item["id"]


@pytest.mark.asyncio
async def test_developer_requests_own_fix_through_approval_only(monkeypatch, client, db_session):
    from app.services import fix_pr_service
    record = await _create_failure(db_session)

    def no_github(*args, **kwargs):
        raise AssertionError("Requesting an approval must not execute GitHub calls")
    monkeypatch.setattr(fix_pr_service.github_tool, "create_branch", no_github)
    first = client.post(f"/api/v1/workflow-failures/{record.id}/create-fix-pr", headers=_auth_headers())
    assert first.status_code == 200 and first.json()["status"] == "approval_required"
    second = client.post(f"/api/v1/workflow-failures/{record.id}/create-fix-pr", headers=_auth_headers())
    assert second.json()["approval_id"] == first.json()["approval_id"]
    approval = await db_session.get(ApprovalRequest, first.json()["approval_id"])
    assert approval.requested_by == "workflow-failure-test-user" and approval.expires_at is not None


@pytest.mark.asyncio
async def test_webhook_and_legacy_failures_are_admin_only(client, db_session):
    await create_workflow_failure(db_session, repo_full_name="octo-org/demo-app", workflow_run_id=42,
                                  requested_by="github_webhook")
    await create_workflow_failure(db_session, repo_full_name="octo-org/demo-app", workflow_run_id=43)
    assert client.get("/api/v1/workflow-failures", headers=_auth_headers()).json() == []
    assert len(client.get("/api/v1/workflow-failures", headers=_auth_headers("admin")).json()) == 2


@pytest.mark.parametrize("path,payload", [
    ("sync", {"repo_full_name": "https://bad.example/repo"}),
    ("sync", {"repo_full_name": "owner/repo?x=1"}),
    ("sync", {"repo_full_name": "owner/repo", "limit": -1}),
    ("import", {"repo_full_name": "owner/repo", "workflow_run_id": 0, "log_text": "error"}),
])
def test_invalid_imports_are_rejected(client, path, payload):
    assert client.post(f"/api/v1/workflow-failures/{path}", json=payload, headers=_auth_headers()).status_code == 422


def test_sync_reports_github_error_and_import_reports_missing_model(monkeypatch, client):
    from app.tools import github_tool
    from app.services import failure_prediction_service

    def unavailable(*args, **kwargs):
        raise github_tool.GitHubToolError("Repository not found or private.")
    monkeypatch.setattr(github_tool, "list_failed_workflow_runs", unavailable)
    assert client.post("/api/v1/workflow-failures/sync", headers=_auth_headers(),
                       json={"repo_full_name": "owner/repo"}).status_code == 400

    def missing_model(*args, **kwargs):
        raise failure_prediction_service.FailurePredictionUnavailable("Model unavailable.")
    monkeypatch.setattr(failure_prediction_service, "predict_failure", missing_model)
    response = client.post("/api/v1/workflow-failures/import", headers=_auth_headers(),
                           json={"repo_full_name": "owner/repo", "workflow_run_id": 1, "log_text": "error"})
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_sync_uses_installation_access_case_insensitively(monkeypatch, client, db_session):
    from app.core.config import settings
    from app.models.models import RepositoryInstallation
    from app.services import workflow_failure_import_service as importer
    from app.services import failure_prediction_service
    from app.tools import github_tool
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "")
    db_session.add(RepositoryInstallation(
        installation_id=77, repo_full_name="Owner/Project", owner="Owner", repo="Project", status="active",
    ))
    await db_session.flush()
    monkeypatch.setattr(importer, "get_installation_access_token", lambda identifier: "synthetic-installation-token")

    def list_runs(repo, limit, *, token):
        assert token == "synthetic-installation-token"
        return [_run()]

    def download(repo, run_id, *, token):
        assert token == "synthetic-installation-token"
        return "npm ERR! Missing script: test"
    monkeypatch.setattr(github_tool, "list_failed_workflow_runs", list_runs)
    monkeypatch.setattr(github_tool, "download_workflow_logs", download)
    monkeypatch.setattr(failure_prediction_service, "predict_failure", lambda log: {
        "label": "npm_missing_test_script", "confidence": 0.92, "suggested_fix": "Add a test script.",
    })
    response = client.post("/api/v1/workflow-failures/sync", headers=_auth_headers(),
                           json={"repo_full_name": "owner/project"})
    assert response.status_code == 200 and response.json()["diagnosed"] == 1
    assert response.json()["failures"][0]["diagnosis_error"] is None


@pytest.mark.asyncio
async def test_expired_fix_approval_can_be_requested_again(client, db_session):
    from datetime import datetime, timedelta, timezone
    record = await _create_failure(db_session)
    path = f"/api/v1/workflow-failures/{record.id}"
    first = client.post(f"{path}/create-fix-pr", headers=_auth_headers())
    assert first.status_code == 200
    assert client.get(path, headers=_auth_headers()).json()["has_pending_approval"] is True
    approval = await db_session.get(ApprovalRequest, first.json()["approval_id"])
    approval.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.flush()
    assert client.get(path, headers=_auth_headers()).json()["has_pending_approval"] is False
    second = client.post(f"{path}/create-fix-pr", headers=_auth_headers())
    assert second.status_code == 200
    assert second.json()["approval_id"] != first.json()["approval_id"]
    assert client.get(path, headers=_auth_headers()).json()["has_pending_approval"] is True
