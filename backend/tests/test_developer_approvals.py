"""Developer CI/CD actions and ownership-scoped human approval regressions."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import approvals, cicd, executions, repositories
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import UserRole, create_access_token
from app.models.models import ApprovalRequest, Execution, User


@pytest_asyncio.fixture
async def developer_app(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DESKTOP_MODE", False)
    monkeypatch.setattr(settings, "DISABLE_AUTH", False)
    monkeypatch.setattr(settings, "ENABLE_HITL", True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'developer-reviews.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    identities = {}
    async with sessions() as db:
        for name, role in [
            ("alice", UserRole.DEVELOPER), ("bob", UserRole.DEVELOPER),
            ("admin", UserRole.ADMIN),
        ]:
            user = User(email=f"{name}@example.com", username=name, role=role,
                        hashed_password="unused-test-password-hash", is_active=True)
            db.add(user)
            await db.flush()
            identities[name] = {"id": user.id, "role": role.value, "username": name, "user_version": 0}
        await db.commit()

    async def override_db():
        async with sessions() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    app = FastAPI()
    for router, prefix in [
        (approvals.router, "approvals"), (repositories.router, "repositories"),
        (cicd.router, "cicd"), (executions.router, "audit"),
    ]:
        app.include_router(router, prefix=f"/api/v1/{prefix}")
    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, sessions, identities
    finally:
        await engine.dispose()


def auth_headers(identities, name="alice", **claims):
    identity = identities[name]
    token = create_access_token({"sub": identity["id"], **identity, **claims})
    return {"Authorization": f"Bearer {token}"}


async def seed_request(sessions, actor="alice", tool="github_create_workflow_pr", **kwargs):
    async with sessions() as db:
        record = ApprovalRequest(
            id=str(uuid4()), requested_by=actor, tool_name=tool,
            tool_input=json.dumps(kwargs.pop("tool_input", {
                "repo_full_name": "example/demo", "container_name": "dev-app",
            })),
            action="Review my work", risk_level="high", summary=f"Work by {actor}", status="pending",
            expires_at=kwargs.pop("expires_at", datetime.now(timezone.utc) + timedelta(minutes=10)), **kwargs,
        )
        db.add(record)
        await db.commit()
        return record.id


@pytest.mark.asyncio
@pytest.mark.parametrize("hitl_enabled", [True, False])
async def test_developer_generates_and_approves_own_workflow_pr(developer_app, monkeypatch, hitl_enabled):
    client, sessions, identities = developer_app
    monkeypatch.setattr(settings, "ENABLE_HITL", hitl_enabled)
    calls = []

    async def no_installation(*args):
        return None

    def create_pr(repo_full_name, **kwargs):
        calls.append(repo_full_name)
        return {"repo_full_name": repo_full_name, "branch": "ai-cicd/generated-workflow",
                "workflow_path": ".github/workflows/ai-generated-ci.yml",
                "pull_request_url": "https://github.com/example/demo/pull/1"}

    monkeypatch.setattr(repositories, "get_installation_for_repo", no_installation)
    monkeypatch.setattr(approvals, "get_installation_for_repo", no_installation)
    monkeypatch.setattr("app.tools.github_tool.create_workflow_pr", create_pr)
    response = await client.post("/api/v1/cicd/generate-workflow", headers=auth_headers(identities),
                                 json={"files": ["package.json", "src/App.jsx"]})
    assert response.status_code == 200
    assert "actions/setup-node" in response.json()["workflow_yaml"]
    response = await client.post("/api/v1/repositories/create-workflow-pr", headers=auth_headers(identities),
                                 json={"repo_full_name": "example/demo"})
    assert response.status_code == 200 and response.json()["approval_required"] is True
    approval_id = response.json()["approval_id"]
    assert calls == []
    request = (await client.get(f"/api/v1/approvals/{approval_id}", headers=auth_headers(identities))).json()
    assert request["requested_by"] == "alice" and request["can_approve"] and request["can_reject"]
    response = await client.post(f"/api/v1/approvals/{approval_id}/decide", headers=auth_headers(identities),
                                 json={"approved": True, "note": "Reviewed my workflow"})
    assert response.status_code == 200 and response.json()["execution_status"] == "completed"
    assert calls == ["example/demo"]
    async with sessions() as db:
        record = await db.get(ApprovalRequest, approval_id)
        assert record.status == "approved" and record.decided_by == record.requested_by == "alice"
        execution = await db.get(Execution, response.json()["execution_id"])
        assert execution.requested_by == "alice" and execution.approval_id == approval_id


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [True, False])
async def test_developer_cannot_read_or_decide_other_work_even_with_forged_identity(developer_app, approved):
    client, sessions, identities = developer_app
    own = await seed_request(sessions)
    other = await seed_request(sessions, actor="bob")
    system = await seed_request(sessions, actor="github_webhook")
    # The database identity overrides signed token display claims, and body
    # fields cannot reassign ownership or grant a shared reviewer role.
    headers = auth_headers(identities, username="bob", role="admin")
    for scope in ("all", "mine"):
        response = await client.get("/api/v1/approvals", params={"scope": scope}, headers=headers)
        assert [item["id"] for item in response.json()] == [own]
    for approval_id in (other, system):
        assert (await client.get(f"/api/v1/approvals/{approval_id}", headers=headers)).status_code == 404
        response = await client.post(f"/api/v1/approvals/{approval_id}/decide", headers=headers,
                                     json={"approved": approved, "requested_by": "alice", "role": "admin"})
        assert response.status_code == 404
    async with sessions() as db:
        assert (await db.get(ApprovalRequest, other)).status == "pending"
        assert (await db.get(ApprovalRequest, system)).status == "pending"
        assert (await db.execute(select(Execution))).scalars().all() == []


@pytest.mark.asyncio
async def test_developer_can_reject_own_request_without_execution(developer_app, monkeypatch):
    client, sessions, identities = developer_app

    def unexpected(*args, **kwargs):
        raise AssertionError("A rejected request must not execute")
    monkeypatch.setattr(approvals, "_dispatch_tool", unexpected)
    approval_id = await seed_request(sessions, tool="docker_restart_container")
    response = await client.post(f"/api/v1/approvals/{approval_id}/decide", headers=auth_headers(identities),
                                 json={"approved": False})
    assert response.status_code == 200 and response.json()["status"] == "rejected"
    async with sessions() as db:
        execution = (await db.execute(select(Execution).where(Execution.approval_id == approval_id))).scalar_one()
        assert execution.status == "cancelled" and execution.requested_by == "alice"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", [
    "docker_stop_container", "docker_start_container", "docker_run_container", "execute_shell_command",
    "github_trigger_workflow", "admin_set_user_active", "unknown_tool",
])
@pytest.mark.parametrize("approved", [True, False])
async def test_ownership_does_not_grant_privileged_tool_execution(developer_app, tool, approved):
    client, sessions, identities = developer_app
    approval_id = await seed_request(sessions, tool=tool)
    response = await client.get("/api/v1/approvals", headers=auth_headers(identities))
    assert response.json()[0]["can_approve"] is False
    assert response.json()[0]["can_reject"] == (tool != "admin_set_user_active")
    response = await client.post(f"/api/v1/approvals/{approval_id}/decide", headers=auth_headers(identities),
                                 json={"approved": approved})
    forbidden = approved or tool == "admin_set_user_active"
    assert response.status_code == (403 if forbidden else 200)
    async with sessions() as db:
        assert (await db.get(ApprovalRequest, approval_id)).status == ("pending" if forbidden else "rejected")


@pytest.mark.asyncio
async def test_developer_can_approve_own_safe_fix_pr(developer_app, monkeypatch):
    client, sessions, identities = developer_app
    failure_id = str(uuid4())
    approval_id = await seed_request(sessions, tool="github_create_fix_pr",
                                     tool_input={"workflow_failure_id": failure_id})

    async def create_safe_fix(db, workflow_failure_id, actor, **kwargs):
        assert workflow_failure_id == failure_id
        assert actor == {"username": "alice", "role": "developer"}
        assert kwargs == {"bypass_approval": True, "audit": False}
        return {"status": "fix_pr_created", "pull_request_url": "https://github.com/example/demo/pull/2"}

    monkeypatch.setattr(approvals, "create_fix_pr_for_failure", create_safe_fix)
    response = await client.post(f"/api/v1/approvals/{approval_id}/decide", headers=auth_headers(identities),
                                 json={"approved": True})
    assert response.status_code == 200 and response.json()["execution_status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin"])
async def test_shared_reviewers_keep_access_to_developer_work(developer_app, monkeypatch, role):
    client, sessions, identities = developer_app
    own = await seed_request(sessions)
    other = await seed_request(sessions, actor="bob", tool="docker_restart_container")
    monkeypatch.setattr(approvals, "_dispatch_tool", lambda *args: ("Restarted", "completed"))
    response = await client.get("/api/v1/approvals", headers=auth_headers(identities, role))
    assert {item["id"] for item in response.json()} == {own, other}
    response = await client.post(f"/api/v1/approvals/{other}/decide", headers=auth_headers(identities, role),
                                 json={"approved": True})
    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["operator", "viewer", "unknown", ""])
async def test_retired_or_unknown_roles_cannot_access_work(developer_app, role):
    client, sessions, identities = developer_app
    approval_id = await seed_request(sessions)
    # Even correctly signed legacy claims cannot revive a removed role.
    token = create_access_token({"sub": str(uuid4()), "username": "legacy", "role": role})
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/v1/approvals", headers=headers)).status_code == 401
    for approved in (True, False):
        assert (await client.post(f"/api/v1/approvals/{approval_id}/decide", headers=headers,
                                  json={"approved": approved})).status_code == 401
    assert (await client.post("/api/v1/cicd/generate-workflow", headers=headers,
                              json={"files": ["package.json"]})).status_code == 401
    assert (await client.post("/api/v1/repositories/create-workflow-pr", headers=headers,
                              json={"repo_full_name": "example/demo"})).status_code == 401


@pytest.mark.asyncio
async def test_expired_own_request_cannot_execute(developer_app):
    client, sessions, identities = developer_app
    approval_id = await seed_request(sessions, tool="docker_restart_container",
                                     expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    response = await client.post(f"/api/v1/approvals/{approval_id}/decide", headers=auth_headers(identities),
                                 json={"approved": True})
    assert response.status_code == 410
    async with sessions() as db:
        assert (await db.get(ApprovalRequest, approval_id)).status == "timed_out"


@pytest.mark.asyncio
async def test_concurrent_developer_and_admin_decisions_execute_once(developer_app, monkeypatch):
    client, sessions, identities = developer_app
    approval_id = await seed_request(sessions, tool="docker_restart_container")
    calls = []

    def dispatch(*args):
        calls.append(args)
        return "Restarted", "completed"
    monkeypatch.setattr(approvals, "_dispatch_tool", dispatch)
    responses = await asyncio.gather(*[
        client.post(f"/api/v1/approvals/{approval_id}/decide", headers=auth_headers(identities, name),
                    json={"approved": True}) for name in ("alice", "admin")
    ])
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert len(calls) == 1
    async with sessions() as db:
        execution = (await db.execute(select(Execution).where(Execution.approval_id == approval_id))).scalar_one()
        assert execution.status == "completed" and execution.requested_by == "alice"


@pytest.mark.asyncio
async def test_workflow_pr_repeated_requests_are_deduplicated_and_private(developer_app):
    client, sessions, identities = developer_app
    payload = {"repo_full_name": "Example/Demo"}
    responses = await asyncio.gather(*[
        client.post("/api/v1/repositories/create-workflow-pr", headers=auth_headers(identities), json=payload)
        for _ in range(4)
    ])
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()["approval_id"] for r in responses}) == 1
    own_id = responses[0].json()["approval_id"]
    for name, code in [("alice", 200), ("admin", 200), ("bob", 404)]:
        response = await client.get("/api/v1/repositories/workflow-pr-status", headers=auth_headers(identities, name),
                                    params={"repo_full_name": "example/demo", "approval_id": own_id})
        assert response.status_code == code
        if code == 200:
            assert response.json()["approval_id"] == own_id
    wrong_repo = await client.get("/api/v1/repositories/workflow-pr-status", headers=auth_headers(identities, "admin"),
                                  params={"repo_full_name": "example/other", "approval_id": own_id})
    assert wrong_repo.status_code == 404
    for name in ["bob", "admin"]:
        result = await client.get("/api/v1/repositories/workflow-pr-status", headers=auth_headers(identities, name),
                                  params={"repo_full_name": "example/demo"})
        assert result.status_code == 200 and result.json() is None
    async with sessions() as db:
        rows = (await db.execute(select(ApprovalRequest))).scalars().all()
        assert len(rows) == 1 and rows[0].id == own_id
        rows[0].expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    result = await client.get("/api/v1/repositories/workflow-pr-status", headers=auth_headers(identities),
                              params={"repo_full_name": "example/demo"})
    assert result.json()["status"] == "timed_out" and not result.json()["approval_required"]
    renewed = await client.post(
        "/api/v1/repositories/create-workflow-pr", headers=auth_headers(identities), json=payload,
    )
    assert renewed.json()["approval_id"] != own_id
    async with sessions() as db:
        assert (await db.get(ApprovalRequest, own_id)).status == "timed_out"
        original = await db.scalar(select(Execution).where(Execution.approval_id == own_id))
        assert original.status == "cancelled" and original.completed_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_workflow_pr_status_exposes_execution_and_retry(developer_app, monkeypatch, fail):
    from app.tools import github_tool
    client, sessions, identities = developer_app
    calls = []

    def create_pr(repo, **kwargs):
        calls.append(repo)
        if fail:
            raise github_tool.GitHubToolError("GitHub token is not configured.")
        return {"repo_full_name": repo, "branch": "ai-cicd/setup-pipeline",
                "workflow_path": ".github/workflows/ai-generated-ci.yml",
                "pull_request_url": "https://github.com/example/demo/pull/7"}
    monkeypatch.setattr(github_tool, "create_workflow_pr", create_pr)
    response = await client.post("/api/v1/repositories/create-workflow-pr", headers=auth_headers(identities),
                                 json={"repo_full_name": "example/demo"})
    approval_id = response.json()["approval_id"]
    assert calls == []
    decided = await client.post(f"/api/v1/approvals/{approval_id}/decide", headers=auth_headers(identities),
                                json={"approved": True})
    assert decided.status_code == 200 and calls == ["example/demo"]
    response = await client.get("/api/v1/repositories/workflow-pr-status", headers=auth_headers(identities),
                                params={"repo_full_name": "example/demo"})
    result = response.json()
    assert result["status"] == ("failed" if fail else "completed")
    assert result["execution_status"] == result["status"] and not result["approval_required"]
    if fail:
        assert "token is not configured" in result["message"] and not result["pull_request_url"]
    else:
        assert result["pull_request_url"].endswith('/pull/7')
    async with sessions() as db:
        requests = (await db.execute(select(Execution).where(Execution.approval_id == approval_id))).scalars().all()
        assert len(requests) == 2 and all(r.status != "pending" for r in requests)
    if fail:
        retry = await client.post("/api/v1/repositories/create-workflow-pr", headers=auth_headers(identities),
                                  json={"repo_full_name": "example/demo"})
        assert retry.json()["approval_id"] != approval_id and calls == ["example/demo"]


@pytest.mark.asyncio
async def test_workflow_pr_rejection_updates_request_and_all_writes_require_approval(developer_app, monkeypatch):
    client, sessions, identities = developer_app
    monkeypatch.setattr(settings, "ENABLE_HITL", False)
    response = await client.post("/api/v1/repositories/create-workflow-pr", headers=auth_headers(identities, "admin"),
                                 json={"repo_full_name": "example/demo"})
    assert response.json()["approval_required"]
    approval_id = response.json()["approval_id"]
    await client.post(f"/api/v1/approvals/{approval_id}/decide", headers=auth_headers(identities, "admin"),
                      json={"approved": False})
    status = await client.get("/api/v1/repositories/workflow-pr-status", headers=auth_headers(identities, "admin"),
                              params={"repo_full_name": "example/demo"})
    assert status.json()["status"] == "rejected" and not status.json()["pull_request_url"]
    async with sessions() as db:
        original = await db.scalar(select(Execution).where(
            Execution.approval_id == approval_id, Execution.source == "api",
        ))
        assert original.status == "cancelled" and original.completed_at is not None
