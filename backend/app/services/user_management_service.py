"""Deterministic safeguards for approval-gated account status changes."""
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import UserRole
from app.models.models import User, UserSession


async def validate_status_change(
    db: AsyncSession, user_id: str, is_active: bool, current_user: dict, *, lock: bool = False
) -> User:
    # Lock admins in a consistent order before the target to prevent concurrent
    # changes from removing the last active admin (PostgreSQL row locking).
    admin_query = select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True)).order_by(User.id)
    if lock:
        admin_query = admin_query.with_for_update().execution_options(populate_existing=True)
    admins = list((await db.execute(admin_query)).scalars().all())
    query = select(User).where(User.id == user_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    user = (await db.execute(query)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.is_active == is_active:
        raise HTTPException(status_code=409, detail="Account status has already changed. Refresh the directory.")
    if not is_active:
        if user.id == current_user.get("sub") or user.username == current_user.get("username"):
            raise HTTPException(status_code=409, detail="You cannot deactivate your own account.")
        if user.role == UserRole.ADMIN and len(admins) <= 1:
            raise HTTPException(status_code=409, detail="At least one active administrator must remain.")
    return user


async def apply_status_change(db: AsyncSession, tool_input: dict, current_user: dict) -> dict:
    user = await validate_status_change(
        db, tool_input["user_id"], tool_input["is_active"], current_user, lock=True
    )
    if user.token_version != tool_input["expected_account_revision"]:
        raise HTTPException(status_code=409, detail="Account changed after this request. Create a new request.")
    user.is_active = tool_input["is_active"]
    if not user.is_active:
        user.token_version += 1
        await db.execute(update(UserSession).where(UserSession.user_id == user.id).values(is_revoked=True))
    await db.flush()
    return {"user_id": user.id, "username": user.username, "is_active": user.is_active}
