"""Account status approval, session revocation, and admin safety regressions."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import approvals, auth, executions
from app.core.config import settings
from app.core.database import Base, ensure_schema_compatibility, get_db
from app.core.security import UserRole, create_access_token, hash_password
from app.models.models import ApprovalRequest, Execution, User, UserSession
from app.services.user_management_service import validate_status_change


@pytest_asyncio.fixture
async def account_app(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DESKTOP_MODE", False)
    monkeypatch.setattr(settings, "DISABLE_AUTH", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "COOKIE_SECURE", False)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'accounts.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    people = {}
    async with sessions() as db:
        for name, role in [
            ("admin", UserRole.ADMIN), ("member", UserRole.DEVELOPER), ("second-member", UserRole.DEVELOPER),
        ]:
            user = User(
                email=f"{name}@example.com", username=name,
                hashed_password=hash_password("account-test-password"), role=role, is_active=True,
            )
            db.add(user)
            await db.flush()
            people[name] = {"id": user.id, "token": create_access_token({
                "sub": user.id, "username": name, "role": role.value, "user_version": user.token_version,
            })}
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
    app.include_router(auth.router, prefix="/api/v1/auth")
    app.include_router(approvals.router, prefix="/api/v1/approvals")
    app.include_router(executions.router, prefix="/api/v1/audit")
    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            yield client, sessions, people
    finally:
        await engine.dispose()


def headers(person):
    return {"Authorization": f"Bearer {person['token']}"}


async def request_change(client, people, active):
    response = await client.post(
        f"/api/v1/auth/users/{people['member']['id']}/status-requests",
        json={"is_active": active}, headers=headers(people["admin"]),
    )
    assert response.status_code == 202
    return response.json()["approval_id"]


async def decide(client, people, approval_id, approved=True, role="admin"):
    return await client.post(
        f"/api/v1/approvals/{approval_id}/decide", json={"approved": approved}, headers=headers(people[role]),
    )


@pytest.mark.asyncio
async def test_admin_cannot_create_another_administrator(account_app):
    client, sessions, people = account_app
    payload = {"email": "second-admin@example.com", "username": "second-admin",
               "password": "account-test-password", "role": "admin"}
    response = await client.post("/api/v1/auth/users", json=payload, headers=headers(people["admin"]))
    assert response.status_code == 422
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 403
    async with sessions() as db:
        admins = (await db.execute(select(User).where(User.role == UserRole.ADMIN))).scalars().all()
        assert len(admins) == 1 and admins[0].id == people["admin"]["id"]
        assert (await db.execute(select(User).where(User.username == "second-admin"))).scalar_one_or_none() is None
    schema = (await client.get("/openapi.json")).json()["components"]["schemas"]["AdminCreateUser"]
    assert schema["properties"]["role"]["const"] == "developer"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["developer"])
async def test_admin_can_still_create_supported_member_roles(account_app, role):
    client, sessions, people = account_app
    response = await client.post("/api/v1/auth/users", headers=headers(people["admin"]), json={
        "email": f"new-{role}@example.com", "username": f"new-{role}",
        "password": "account-test-password", "role": role,
    })
    assert response.status_code == 201 and response.json()["role"] == role
    async with sessions() as db:
        user = await db.get(User, response.json()["id"])
        assert user.role.value == role and user.is_active


@pytest.mark.asyncio
async def test_user_creation_service_cannot_bypass_admin_role_restriction(account_app):
    from fastapi import HTTPException

    _, sessions, _ = account_app
    async with sessions() as db:
        with pytest.raises(HTTPException) as error:
            await auth._create_user_record(
                db, email="blocked-admin@example.com", username="blocked-admin",
                password="account-test-password", role=UserRole.ADMIN,
            )
        assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_bootstrap_creates_only_initial_admin_even_if_configuration_changes(isolated_app_database, monkeypatch):
    from app.core.database import ensure_default_users

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "DEFAULT_ADMIN_USERNAME", "initial-admin")
    monkeypatch.setattr(settings, "DEFAULT_ADMIN_EMAIL", "initial-admin@example.com")
    monkeypatch.setattr(settings, "DEFAULT_ADMIN_PASSWORD", "bootstrap-test-password")
    async with isolated_app_database() as db:
        created, _ = await ensure_default_users(db)
        assert created == ["initial-admin"]
        first = (await db.execute(select(User).where(User.role == UserRole.ADMIN))).scalar_one()
        first.is_active = False
        await db.commit()
        monkeypatch.setattr(settings, "DEFAULT_ADMIN_USERNAME", "changed-admin")
        monkeypatch.setattr(settings, "DEFAULT_ADMIN_EMAIL", "changed-admin@example.com")
        created, _ = await ensure_default_users(db)
        assert created == []
        admins = (await db.execute(select(User).where(User.role == UserRole.ADMIN))).scalars().all()
        assert len(admins) == 1 and admins[0].id == first.id and admins[0].is_active is False


@pytest.mark.asyncio
async def test_deactivation_requires_approval_and_invalidates_existing_sessions(account_app):
    client, sessions, people = account_app
    login = await client.post("/api/v1/auth/login", json={
        "email": "member@example.com", "password": "account-test-password",
    })
    assert login.status_code == 200
    old_access = {"Authorization": f"Bearer {login.json()['access_token']}"}
    refresh_token = login.json()["refresh_token"]
    approval_id = await request_change(client, people, False)
    assert (await client.get("/api/v1/audit", headers=old_access)).status_code == 200
    async with sessions() as db:
        assert (await db.get(User, people["member"]["id"])).is_active is True
        request = await db.get(ApprovalRequest, approval_id)
        assert request.status == "pending" and request.risk_level == "high"
        assert json.loads(request.tool_input)["user_id"] == people["member"]["id"]
    decision = await decide(client, people, approval_id)
    assert decision.status_code == 200
    assert decision.json()["execution_status"] == "completed"
    assert (await client.get("/api/v1/audit", headers=old_access)).status_code == 401
    assert (await client.get("/api/v1/auth/me")).status_code == 401  # existing cookie
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})).status_code == 401
    assert (await client.post("/api/v1/auth/login", json={
        "email": "member@example.com", "password": "account-test-password",
    })).status_code == 403
    async with sessions() as db:
        user = await db.get(User, people["member"]["id"])
        assert user.is_active is False and user.token_version == 1
        user_sessions = (await db.execute(select(UserSession).where(UserSession.user_id == user.id))).scalars().all()
        assert user_sessions and all(session.is_revoked for session in user_sessions)
        audit = (await db.execute(select(Execution).where(Execution.approval_id == approval_id))).scalar_one()
        assert audit.requested_by == "admin" and audit.status == "completed"

    activation_id = await request_change(client, people, True)
    assert (await decide(client, people, activation_id)).status_code == 200
    assert (await client.get("/api/v1/audit", headers=old_access)).status_code == 401
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})).status_code == 401
    fresh_login = await client.post("/api/v1/auth/login", json={
        "email": "member@example.com", "password": "account-test-password",
    })
    assert fresh_login.status_code == 200
    new_access = {"Authorization": f"Bearer {fresh_login.json()['access_token']}"}
    assert (await client.get("/api/v1/audit", headers=new_access)).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["member", "second-member"])
async def test_only_admins_can_request_or_decide_account_changes(account_app, role):
    client, _, people = account_app
    response = await client.post(
        f"/api/v1/auth/users/{people['member']['id']}/status-requests",
        json={"is_active": False}, headers=headers(people[role]),
    )
    assert response.status_code == 403
    approval_id = await request_change(client, people, False)
    expected_status = 404
    assert (await decide(client, people, approval_id, role=role)).status_code == expected_status
    assert (await decide(client, people, approval_id, approved=False, role=role)).status_code == expected_status


@pytest.mark.asyncio
async def test_rejected_and_expired_requests_do_not_change_account_status(account_app):
    client, sessions, people = account_app
    approval_id = await request_change(client, people, False)
    assert (await decide(client, people, approval_id, approved=False)).status_code == 200
    expired_id = await request_change(client, people, False)
    async with sessions() as db:
        approval = await db.get(ApprovalRequest, expired_id)
        approval.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    assert (await decide(client, people, expired_id)).status_code == 410
    async with sessions() as db:
        assert (await db.get(User, people["member"]["id"])).is_active is True


@pytest.mark.asyncio
async def test_self_deactivation_and_last_admin_are_protected(account_app):
    client, sessions, people = account_app
    response = await client.post(
        f"/api/v1/auth/users/{people['admin']['id']}/status-requests",
        json={"is_active": False}, headers=headers(people["admin"]),
    )
    assert response.status_code == 409
    async with sessions() as db:
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as error:
            await validate_status_change(db, people["admin"]["id"], False, {"sub": str(uuid4())})
        assert "active administrator" in error.value.detail


@pytest.mark.asyncio
async def test_stale_approval_cannot_apply_after_account_changed(account_app):
    client, sessions, people = account_app
    first = await request_change(client, people, False)
    stale = await request_change(client, people, False)
    assert (await decide(client, people, first)).status_code == 200
    activation = await request_change(client, people, True)
    assert (await decide(client, people, activation)).status_code == 200
    assert (await decide(client, people, stale)).status_code == 409
    async with sessions() as db:
        assert (await db.get(User, people["member"]["id"])).is_active is True


@pytest.mark.asyncio
async def test_completed_account_decision_cannot_be_changed_or_executed_again(account_app):
    client, sessions, people = account_app
    approval_id = await request_change(client, people, False)
    assert (await decide(client, people, approval_id)).status_code == 200
    assert (await decide(client, people, approval_id)).status_code == 409
    assert (await decide(client, people, approval_id, approved=False)).status_code == 409
    async with sessions() as db:
        user = await db.get(User, people["member"]["id"])
        assert user.is_active is False and user.token_version == 1
        assert (await db.get(ApprovalRequest, approval_id)).status == "approved"
        results = (await db.execute(select(Execution).where(Execution.approval_id == approval_id))).scalars().all()
        assert len(results) == 1


@pytest.mark.asyncio
async def test_concurrent_approval_and_rejection_only_apply_one_decision(account_app):
    client, sessions, people = account_app
    approval_id = await request_change(client, people, False)
    responses = await asyncio.gather(
        decide(client, people, approval_id),
        decide(client, people, approval_id, approved=False),
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    accepted = next(response.json()["status"] for response in responses if response.status_code == 200)
    async with sessions() as db:
        assert (await db.get(ApprovalRequest, approval_id)).status == accepted
        assert (await db.get(User, people["member"]["id"])).is_active == (accepted == "rejected")
        results = (await db.execute(select(Execution).where(Execution.approval_id == approval_id))).scalars().all()
        assert len(results) == 1


@pytest.mark.asyncio
async def test_legacy_tokens_for_registered_accounts_are_revoked(account_app):
    client, _, people = account_app
    token = create_access_token({"sub": people["member"]["id"], "username": "member", "role": "developer"})
    legacy = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/v1/audit", headers=legacy)).status_code == 200
    change = await request_change(client, people, False)
    assert (await decide(client, people, change)).status_code == 200
    activate = await request_change(client, people, True)
    assert (await decide(client, people, activate)).status_code == 200
    assert (await client.get("/api/v1/audit", headers=legacy)).status_code == 401


@pytest.mark.asyncio
async def test_schema_compatibility_upgrades_existing_users_table():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE users (id TEXT PRIMARY KEY)"))
        await conn.execute(text("CREATE TABLE workflow_failures (id TEXT PRIMARY KEY)"))
        await conn.execute(text("INSERT INTO users (id) VALUES ('existing')"))
        await ensure_schema_compatibility(conn)
        await ensure_schema_compatibility(conn)  # safe to run again at startup
        assert (await conn.execute(text("SELECT token_version FROM users"))).scalar_one() == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_deactivated_member_cannot_start_websocket_actions(account_app, monkeypatch):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from app.api.routes import agent

    client, sessions, people = account_app
    approval_id = await request_change(client, people, False)
    assert (await decide(client, people, approval_id)).status_code == 200
    monkeypatch.setattr(agent, "AsyncSessionLocal", sessions)
    app = FastAPI()
    app.add_api_websocket_route("/ws/agent", agent.agent_ws)
    with TestClient(app) as socket_client:
        with pytest.raises(WebSocketDisconnect) as error:
            with socket_client.websocket_connect("/ws/agent", headers=headers(people["member"])):
                pass
        assert error.value.code == 4003


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["operator", "viewer"])
async def test_retired_roles_cannot_be_created(account_app, role):
    client, sessions, people = account_app
    payload = {"email": "retired@example.com", "username": "retired",
               "password": "account-test-password", "role": role}
    for path in ("/api/v1/auth/register", "/api/v1/auth/users"):
        response = await client.post(path, json=payload, headers=headers(people["admin"]))
        assert response.status_code == 422
    async with sessions() as db:
        assert await db.scalar(select(User.id).where(User.username == "retired")) is None


@pytest.mark.asyncio
async def test_signup_needs_no_role_and_only_two_roles_are_advertised(account_app):
    client, _, _ = account_app
    roles = (await client.get("/api/v1/auth/roles")).json()
    assert [role["role"] for role in roles["roles"]] == ["admin", "developer"]
    assert roles["public_signup_roles"] == ["developer"]
    response = await client.post("/api/v1/auth/register", json={
        "email": "signup@example.com", "username": "signup", "password": "account-test-password",
    })
    assert response.status_code == 201
    assert response.json()["user"]["role"] == "developer"
    assert (await client.get("/api/v1/auth/users")).status_code == 403
