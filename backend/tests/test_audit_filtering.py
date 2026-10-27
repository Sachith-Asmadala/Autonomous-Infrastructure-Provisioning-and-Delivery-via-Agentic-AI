"""Test audit filtering API."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes import approvals, executions
from app.core.database import Base, get_db
from app.core.config import settings
from app.core.security import create_access_token
from app.models.models import ApprovalRequest, Execution


TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = async_sessionmaker(test_engine, expire_on_commit=False)


def _build_test_app() -> FastAPI:
    test_app = FastAPI(title="Audit Filtering Test App")
    test_app.include_router(executions.router, prefix="/api/v1/audit")
    test_app.include_router(executions.router, prefix="/api/v1/executions")
    test_app.include_router(approvals.router, prefix="/api/v1/approvals")
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
async def override_db(db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "DESKTOP_MODE", False)
    monkeypatch.setattr(settings, "DISABLE_AUTH", False)

    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    yield
    app.dependency_overrides.pop(get_db, None)


def _auth_headers(role: str = "admin", username: str = "test_user") -> dict[str, str]:
    token = create_access_token(
        {
            "sub": str(uuid.uuid4()),
            "username": username,
            "role": role,
        }
    )
    return {"Authorization": f"Bearer {token}"}


async def _seed_execution(
    db_session: AsyncSession,
    *,
    tool_name: str,
    requested_by: str = "test_user",
    status: str = "completed",
    summary: str | None = None,
    started_at: datetime | None = None,
) -> Execution:
    now = started_at or datetime.now(tz=timezone.utc)
    execution = Execution(
        id=str(uuid.uuid4()),
        session_id=f"session-{tool_name}-{uuid.uuid4()}",
        requested_by=requested_by,
        tool_name=tool_name,
        tool_input="{}",
        status=status,
        summary=summary or f"Test {tool_name}",
        details="{}",
        source="api",
        started_at=now,
        completed_at=now,
    )
    db_session.add(execution)
    await db_session.flush()
    return execution


@pytest.mark.asyncio
async def test_executions_filter_by_tool(db_session: AsyncSession):
    await _seed_execution(db_session, tool_name="failure_prediction_model")
    await _seed_execution(db_session, tool_name="github_workflow_pr")
    await _seed_execution(db_session, tool_name="github_fix_pr")

    result = await db_session.execute(select(Execution).where(Execution.tool_name == "failure_prediction_model"))
    records = result.scalars().all()

    assert len(records) >= 1
    assert all(record.tool_name == "failure_prediction_model" for record in records)


@pytest.mark.asyncio
async def test_executions_filter_by_status(db_session: AsyncSession):
    await _seed_execution(db_session, tool_name="status_tool", status="completed")
    await _seed_execution(db_session, tool_name="status_tool", status="failed")
    await _seed_execution(db_session, tool_name="status_tool", status="completed")

    result = await db_session.execute(select(Execution).where(Execution.status == "completed"))
    records = result.scalars().all()

    assert len(records) >= 1
    assert all(record.status == "completed" for record in records)


@pytest.mark.asyncio
async def test_executions_filter_by_days(db_session: AsyncSession):
    now = datetime.now(tz=timezone.utc)
    await _seed_execution(
        db_session,
        tool_name="date_tool",
        summary="Old execution",
        started_at=now - timedelta(days=10),
    )
    await _seed_execution(db_session, tool_name="date_tool", summary="New execution", started_at=now)

    cutoff = now - timedelta(days=3)
    result = await db_session.execute(select(Execution).where(Execution.started_at >= cutoff))
    records = result.scalars().all()

    assert any(record.summary == "New execution" for record in records)
    assert all(record.summary != "Old execution" for record in records)


@pytest.mark.asyncio
async def test_audit_endpoint_filters_by_tool_and_success_alias(db_session: AsyncSession):
    await _seed_execution(db_session, tool_name="github_log_downloader", status="completed")
    await _seed_execution(db_session, tool_name="failure_prediction_model", status="failed")

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/audit?limit=50&tool=github&status=success",
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["tool_name"] == "github_log_downloader"
    assert body[0]["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["developer"])
@pytest.mark.parametrize("prefix", ["/api/v1/audit", "/api/v1/executions"])
async def test_member_activity_is_owned_even_with_actor_override(db_session, role, prefix):
    own = await _seed_execution(db_session, tool_name="own_tool")
    other = await _seed_execution(db_session, tool_name="other_tool", requested_by="other_user")
    await _seed_execution(db_session, tool_name="webhook_tool", requested_by="github_webhook")
    with TestClient(app) as client:
        headers = _auth_headers(role)
        response = client.get(prefix, headers=headers)
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [own.id]
        for actor in ("other_user", "github_webhook", "%"):
            response = client.get(prefix, params={"actor": actor, "days": 0}, headers=headers)
            assert response.status_code == 200
            assert response.json() == []
        assert client.get(f"{prefix}/{own.id}", headers=headers).status_code == 200
        assert client.get(f"{prefix}/{other.id}", headers=headers).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["/api/v1/audit", "/api/v1/executions"])
async def test_admin_can_read_and_filter_all_actors(db_session, prefix):
    own = await _seed_execution(db_session, tool_name="own_tool")
    other = await _seed_execution(db_session, tool_name="other_tool", requested_by="other_user")
    system = await _seed_execution(db_session, tool_name="webhook_tool", requested_by="github_webhook")
    with TestClient(app) as client:
        headers = _auth_headers("admin")
        response = client.get(prefix, headers=headers)
        assert response.status_code == 200
        assert {item["id"] for item in response.json()} == {own.id, other.id, system.id}
        response = client.get(prefix, params={"actor": "other_user"}, headers=headers)
        assert [item["id"] for item in response.json()] == [other.id]
        assert response.json()[0]["requested_by"] == "other_user"
        assert client.get(f"{prefix}/{other.id}", headers=headers).status_code == 200


@pytest.mark.asyncio
async def test_member_ownership_supports_subject_fallback_and_missing_identity_fails_closed(db_session):
    subject = str(uuid.uuid4())
    own = await _seed_execution(db_session, tool_name="legacy_tool", requested_by=subject)
    await _seed_execution(db_session, tool_name="other_tool")
    with TestClient(app) as client:
        token = create_access_token({"sub": subject, "role": "developer"})
        response = client.get("/api/v1/audit", headers={"Authorization": f"Bearer {token}"})
        assert [item["id"] for item in response.json()] == [own.id]
        token = create_access_token({"role": "developer"})
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/audit", headers=headers).status_code == 401
        assert client.get(f"/api/v1/executions/{own.id}", headers=headers).status_code == 401
        assert client.get("/api/v1/audit").status_code == 401


async def _seed_approval(db_session, actor="test_user", **kwargs):
    record = ApprovalRequest(
        id=str(uuid.uuid4()), requested_by=actor, tool_name="github_create_workflow_pr",
        action="Create workflow PR", risk_level="high", summary=f"Request by {actor}",
        status="pending", **kwargs,
    )
    db_session.add(record)
    await db_session.flush()
    return record


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["developer"])
async def test_members_only_see_their_own_approval_requests_and_scoped_decisions(db_session, role):
    own = await _seed_approval(db_session)
    other = await _seed_approval(db_session, "other_user")
    with TestClient(app) as client:
        headers = _auth_headers(role)
        for scope in ("all", "mine"):
            response = client.get("/api/v1/approvals", params={"scope": scope}, headers=headers)
            assert response.status_code == 200
            assert [item["id"] for item in response.json()] == [own.id]
            assert response.json()[0]["can_approve"] == (role == "developer")
            assert response.json()[0]["can_reject"] == (role == "developer")
        assert client.get(f"/api/v1/approvals/{own.id}", headers=headers).status_code == 200
        assert client.get(f"/api/v1/approvals/{other.id}", headers=headers).status_code == 404
        target = other
        assert client.post(
            f"/api/v1/approvals/{target.id}/decide", json={"approved": True}, headers=headers,
        ).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin"])
async def test_approval_reviewers_keep_shared_queue_and_can_request_personal_scope(db_session, role):
    own = await _seed_approval(db_session)
    other = await _seed_approval(db_session, "other_user")
    with TestClient(app) as client:
        headers = _auth_headers(role)
        response = client.get("/api/v1/approvals", headers=headers)
        assert {item["id"] for item in response.json()} == {own.id, other.id}
        response = client.get("/api/v1/approvals", params={"scope": "mine"}, headers=headers)
        assert [item["id"] for item in response.json()] == [own.id]
        assert client.get(f"/api/v1/approvals/{other.id}", headers=headers).status_code == 200


@pytest.mark.asyncio
async def test_admin_audit_distinguishes_requester_and_approval_reviewer(db_session):
    approval = await _seed_approval(db_session, decided_by="operator_user")
    approval.status = "approved"
    execution = await _seed_execution(db_session, tool_name="github_create_workflow_pr")
    execution.approval_id = approval.id
    await db_session.flush()
    with TestClient(app) as client:
        response = client.get("/api/v1/audit", headers=_auth_headers("admin"))
        item = response.json()[0]
        assert item["requested_by"] == "test_user"
        assert item["approval_decided_by"] == "operator_user"
        assert item["approval_status"] == "approved"
        detail = client.get(f"/api/v1/executions/{execution.id}", headers=_auth_headers("admin"))
        assert detail.json()["approval_decided_by"] == "operator_user"
