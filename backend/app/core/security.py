"""Security utilities: JWT, password hashing, and role-based access control."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional
import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)
ACCESS_TOKEN_COOKIE_NAME = settings.COOKIE_NAME or "devops_access_token"

DESKTOP_USER_ID = "desktop_user"
DESKTOP_USER_EMAIL = "desktop@local.app"
DESKTOP_USER_USERNAME = "desktop_user"


class UserRole(str, Enum):
    DEVELOPER = "developer"
    ADMIN = "admin"


ROLE_LABELS: dict[UserRole, str] = {
    UserRole.ADMIN: "Admin",
    UserRole.DEVELOPER: "Developer",
}

ROLE_DESCRIPTIONS: dict[UserRole, str] = {
    UserRole.ADMIN: (
        "Full platform owner. Can manage users, audit activity, approve changes, and use all agent tools."
    ),
    UserRole.DEVELOPER: (
        "Can build CI/CD workflows, review their own approval requests, and use development/staging tools."
    ),
}

# Public signup creates developers only. The initial admin is bootstrapped;
# neither registration nor member provisioning can grant administrator access.
PUBLIC_SIGNUP_ROLES: set[UserRole] = {UserRole.DEVELOPER}

ROLE_PERMISSIONS: dict[UserRole, list[str]] = {
    UserRole.DEVELOPER: [
        "agent:chat",
        "approvals:read",
        "approvals:decide:own",
        "agents:orchestrate",
        "cicd:read",
        "cicd:generate",
        "failures:predict",
        "repositories:read",
        "repositories:write",
        "workflow_failures:read",
        "executions:read",
        "logs:read",
        "deployments:staging",
    ],
    UserRole.ADMIN: ["*"],
}


def coerce_role(value: str | UserRole | None) -> UserRole:
    """Reject missing, retired, or unknown roles instead of granting access."""
    if isinstance(value, UserRole):
        return value
    try:
        return UserRole(str(value or "").lower())
    except ValueError:
        raise HTTPException(status_code=401, detail="Account role is no longer supported. Sign in again.")


def get_role_permissions(role: str | UserRole | None) -> list[str]:
    try:
        role_value = coerce_role(role)
    except HTTPException:
        return []
    permissions = ROLE_PERMISSIONS.get(role_value, [])
    if "*" in permissions:
        return ["*"]
    return sorted(set(permissions))


def has_permission(role: str | UserRole | None, permission: str) -> bool:
    perms = get_role_permissions(role)
    return "*" in perms or permission in perms


def role_profile(role: str | UserRole | None) -> dict:
    role_value = coerce_role(role)
    return {
        "role": role_value.value,
        "label": ROLE_LABELS[role_value],
        "description": ROLE_DESCRIPTIONS[role_value],
        "permissions": get_role_permissions(role_value),
        "can_self_signup": role_value in PUBLIC_SIGNUP_ROLES,
    }


def auth_bypass_enabled() -> bool:
    """Return true when local desktop mode disables JWT and RBAC checks."""
    return settings.auth_disabled


def desktop_user_payload() -> dict:
    """Synthetic admin user used only for local desktop mode."""
    return {
        "sub": DESKTOP_USER_ID,
        "id": DESKTOP_USER_ID,
        "username": DESKTOP_USER_USERNAME,
        "email": DESKTOP_USER_EMAIL,
        "role": UserRole.ADMIN.value,
        "is_desktop_user": True,
    }


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = _build_token_payload(
        data,
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        token_type="access",
    )
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = _build_token_payload(
        data,
        expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        token_type="refresh",
    )
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _build_token_payload(data: dict, expires_delta: timedelta, token_type: str) -> dict:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire, "type": token_type, "jti": str(uuid.uuid4())})
    return to_encode


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _get_request_token(request: Request, bearer_token: str | None = None) -> str:
    token = bearer_token or request.cookies.get(ACCESS_TOKEN_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def _decode_access_payload(request: Request, bearer_token: str | None = None) -> dict:
    raw_token = _get_request_token(request, bearer_token)
    payload = decode_token(raw_token)
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type.")
    payload["role"] = coerce_role(payload.get("role")).value
    return payload


async def validate_account_payload(payload: dict, db: AsyncSession) -> dict:
    """Enforce persisted account status and invalidate pre-deactivation tokens.

    Newly issued tokens carry a user_version and require an existing account.
    Legacy signed tokens still use their original claims if there is no matching
    account, preserving existing integrations; registered accounts are always
    checked, including legacy tokens with an implicit version of zero.
    """
    from app.models.models import User

    result = await db.execute(
        select(User.is_active, User.token_version, User.role, User.username)
        .where(User.id == str(payload.get("sub", "")))
    )
    user = result.first()
    if user is None:
        if "user_version" in payload:
            raise HTTPException(status_code=401, detail="Account no longer exists. Sign in again.")
        return payload
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Account is deactivated. Contact your administrator.")
    if payload.get("user_version", 0) != user.token_version:
        raise HTTPException(status_code=401, detail="Session revoked. Sign in again.")
    return {**payload, "role": coerce_role(user.role).value, "username": user.username}


def require_permission(permission: str):
    """FastAPI dependency: require a specific permission from bearer token or httpOnly cookie."""

    async def _check(request: Request, token: str | None = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
        if auth_bypass_enabled():
            return desktop_user_payload()
        payload = await validate_account_payload(_decode_access_payload(request, token), db)
        role = coerce_role(payload.get("role"))
        if not has_permission(role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission}' required for this action.",
            )
        return payload

    return _check


def require_role(*roles: UserRole):
    allowed = {role.value for role in roles}

    async def _check(request: Request, token: str | None = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
        if auth_bypass_enabled():
            return desktop_user_payload()
        payload = await validate_account_payload(_decode_access_payload(request, token), db)
        if payload.get("role") not in allowed and payload.get("role") != UserRole.ADMIN.value:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role.")
        return payload

    return _check


async def get_current_user(
    request: Request, token: str | None = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)
) -> dict:
    """Return decoded JWT payload from Authorization bearer or secure httpOnly cookie."""
    if auth_bypass_enabled():
        return desktop_user_payload()
    return await validate_account_payload(_decode_access_payload(request, token), db)
