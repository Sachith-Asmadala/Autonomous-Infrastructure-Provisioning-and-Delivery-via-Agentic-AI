"""Two-role signup, retired account migration, and fail-closed permissions."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import String, cast, select, update

from app.core.database import migrate_retired_roles
from app.core.security import UserRole, coerce_role, create_access_token, get_role_permissions, has_permission
from app.core.security import validate_account_payload
from app.models.models import User, UserSession
from app.agents.tools_registry import get_all_tools


@pytest.mark.parametrize("role", ["operator", "viewer", "unknown", "", None])
def test_unsupported_roles_have_no_permissions_or_tools(role):
    with pytest.raises(HTTPException) as error:
        coerce_role(role)
    assert error.value.status_code == 401
    assert get_role_permissions(role) == []
    assert not has_permission(role, "agent:chat")
    assert get_all_tools(user_role=role) == []


@pytest.mark.asyncio
async def test_migration_preserves_accounts_and_history_and_revokes_sessions(isolated_app_database):
    sessions = isolated_app_database
    ids = {}
    async with sessions() as db:
        for name in ("operator", "viewer", "developer", "admin"):
            user = User(id=str(uuid4()), email=f"{name}@example.com", username=name,
                        hashed_password="unused", role=UserRole.ADMIN if name == "admin" else UserRole.DEVELOPER,
                        is_active=name != "viewer", token_version=2)
            db.add(user)
            await db.flush()
            ids[name] = user.id
            db.add(UserSession(user_id=user.id, refresh_token=create_access_token({"sub": user.id}),
                               expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
            if name in ("operator", "viewer"):
                await db.execute(update(User).where(User.id == user.id).values(role=name))
        await db.commit()
    async with sessions() as db:
        conn = await db.connection()
        await migrate_retired_roles(conn)
        await migrate_retired_roles(conn)
        await db.commit()
    async with sessions() as db:
        for name, user_id in ids.items():
            user = await db.get(User, user_id)
            assert user.username == name and user.is_active == (name != "viewer")
            assert user.role == (UserRole.ADMIN if name == "admin" else UserRole.DEVELOPER)
            migrated = name in ("operator", "viewer")
            assert user.token_version == (3 if migrated else 2)
            session = await db.scalar(select(UserSession).where(UserSession.user_id == user_id))
            assert session.is_revoked == migrated
            if migrated:
                with pytest.raises(HTTPException):
                    await validate_account_payload({"sub": user_id, "user_version": 2, "role": name}, db)
        assert set((await db.execute(select(cast(User.role, String)))).scalars()) == {"admin", "developer"}
