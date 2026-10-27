"""Ownership rules for member activity and administrator audit access."""
from fastapi import HTTPException

from app.core.security import UserRole, coerce_role


def can_view_all_activity(current_user: dict) -> bool:
    return coerce_role(current_user.get("role")) == UserRole.ADMIN


def activity_actor(current_user: dict) -> str:
    """Use the same authenticated identity recorded by action services.

    Existing records use the unique username, falling back to the JWT subject.
    Missing identity must never become an unfiltered query.
    """
    actor = current_user.get("username") or current_user.get("sub")
    if not actor:
        raise HTTPException(status_code=401, detail="Authenticated identity required.")
    return str(actor)
