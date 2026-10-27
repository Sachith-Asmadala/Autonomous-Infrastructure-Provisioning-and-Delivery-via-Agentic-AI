"""Authentication and user-management endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import ensure_default_users, get_db
from app.core.logging import logger
from app.core.security import (
    ACCESS_TOKEN_COOKIE_NAME,
    PUBLIC_SIGNUP_ROLES,
    UserRole,
    auth_bypass_enabled,
    coerce_role,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    require_permission,
    role_profile,
    verify_password,
)
from app.models.models import User, UserSession
from app.schemas.schemas import (
    AdminCreateUser,
    LoginResponse,
    RefreshRequest,
    RolesResponse,
    TokenResponse,
    UserOut,
    UserRegister,
    UserStatusApprovalOut,
    UserStatusChangeRequest,
)
from app.services import audit_service
from app.services.user_management_service import validate_status_change
from app.api.routes.approvals import create_approval_request

router = APIRouter()


def _cookie_secure() -> bool:
    return bool(settings.COOKIE_SECURE)


def _cookie_samesite() -> Literal["lax", "strict", "none"]:
    value = settings.COOKIE_SAMESITE.strip().lower()
    if value in {"lax", "strict", "none"}:
        return cast(Literal["lax", "strict", "none"], value)
    return "lax"


def _set_access_cookie(response: Response, access_token: str) -> None:
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE_NAME,
        value=access_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
        secure=_cookie_secure(),
        httponly=True,
        samesite=_cookie_samesite(),
    )


def _clear_access_cookie(response: Response) -> None:
    response.delete_cookie(
        key=ACCESS_TOKEN_COOKIE_NAME,
        path="/",
        secure=_cookie_secure(),
        httponly=True,
        samesite=_cookie_samesite(),
    )


async def _read_login_payload(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid login payload.")
        return payload

    form = await request.form()
    return {
        "email": form.get("email"),
        "username": form.get("username"),
        "password": form.get("password"),
    }


def _token_payload(user: User) -> dict[str, Any]:
    return {"sub": str(user.id), "role": user.role.value, "username": user.username, "user_version": user.token_version}


def _login_response(user: User, access_token: str, refresh_token: str) -> LoginResponse:
    return LoginResponse(
        user=UserOut.model_validate(user),
        access_token=access_token,
        refresh_token=refresh_token,
        user_id=str(user.id),
        username=user.username,
        role=user.role.value,
    )


async def _ensure_unique_user(db: AsyncSession, email: str, username: str) -> None:
    result = await db.execute(select(User).where(or_(User.email == email, User.username == username)))
    existing = result.scalar_one_or_none()
    if existing:
        if existing.email == email:
            raise HTTPException(status_code=400, detail="Email already registered.")
        raise HTTPException(status_code=400, detail="Username already taken.")


async def _create_user_record(
    db: AsyncSession,
    *,
    email: str,
    username: str,
    password: str,
    role: UserRole,
    is_active: bool = True,
) -> User:
    if role == UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Creating additional administrator accounts is disabled.")
    await _ensure_unique_user(db, email, username)
    user = User(
        email=email,
        username=username,
        hashed_password=hash_password(password),
        role=role,
        is_active=is_active,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def _create_session_and_cookie(
    user: User,
    request: Request,
    response: Response,
    db: AsyncSession,
) -> tuple[str, str]:
    access_token = create_access_token(data=_token_payload(user))
    refresh_token = create_refresh_token(data=_token_payload(user))
    refresh_payload = decode_token(refresh_token)

    db.add(
        UserSession(
            user_id=str(user.id),
            refresh_token=refresh_token,
            expires_at=datetime.fromtimestamp(refresh_payload["exp"], tz=timezone.utc),
            is_revoked=False,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    )
    await db.flush()
    _set_access_cookie(response, access_token)
    return access_token, refresh_token


async def _safe_audit_auth(
    db: AsyncSession,
    *,
    action: str,
    actor: str,
    status: str = "completed",
    tool_input: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Audit auth events without recording credentials or token values."""
    try:
        await audit_service.log_execution(
            db,
            tool_name=action,
            action_summary=action.replace("_", " "),
            status=status,
            actor=actor,
            tool_input=tool_input or {},
            tool_output={},
            error=error,
            source="auth",
        )
    except audit_service.AuditError as exc:
        logger.warning("audit.auth.skipped", action=action, error=str(exc))


@router.get("/roles", response_model=RolesResponse)
async def get_roles():
    """Return role profiles for the login/signup UI."""
    ordered = [UserRole.ADMIN, UserRole.DEVELOPER]
    return {
        "roles": [role_profile(role) for role in ordered],
        "public_signup_roles": [role.value for role in sorted(PUBLIC_SIGNUP_ROLES, key=lambda role: role.value)],
    }


@router.post("/register", response_model=LoginResponse, status_code=201)
async def register(payload: UserRegister, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """
    Public self-signup.

    Only developer accounts can be created publicly. Additional admin creation
    is disabled.
    """
    requested_role = coerce_role(payload.role or UserRole.DEVELOPER)
    if requested_role not in PUBLIC_SIGNUP_ROLES:
        await _safe_audit_auth(
            db,
            action="auth_register",
            actor=payload.username,
            status="failed",
            tool_input={"username": payload.username, "requested_role": requested_role.value},
            error="privileged public signup rejected",
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public sign-up supports only developer accounts.",
        )

    user = await _create_user_record(
        db,
        email=str(payload.email),
        username=payload.username,
        password=payload.password,
        role=requested_role,
        is_active=True,
    )
    access_token, refresh_token = await _create_session_and_cookie(user, request, response, db)
    await _safe_audit_auth(
        db,
        action="auth_register",
        actor=user.username,
        tool_input={"username": user.username, "role": user.role.value},
    )
    return _login_response(user, access_token, refresh_token)


@router.post("/login", response_model=LoginResponse)
async def login(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Login with email/password or legacy username/password and set an httpOnly JWT cookie."""
    payload = await _read_login_payload(request)
    identifier = (payload.get("email") or payload.get("username") or "").strip()
    password = payload.get("password") or ""

    if not identifier or not password:
        raise HTTPException(status_code=422, detail="Email/username and password are required.")

    if settings.ENVIRONMENT.strip().lower() not in {"production", "prod", "release"}:
        created, updated = await ensure_default_users(db)
        if created or updated:
            await db.commit()

    result = await db.execute(select(User).where(or_(User.email == identifier, User.username == identifier)))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        await _safe_audit_auth(
            db,
            action="auth_login",
            actor=identifier or "unknown",
            status="failed",
            tool_input={"identifier": identifier},
            error="invalid credentials",
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        await _safe_audit_auth(
            db,
            action="auth_login",
            actor=user.username,
            status="failed",
            tool_input={"username": user.username},
            error="account deactivated",
        )
        await db.commit()
        raise HTTPException(status_code=403, detail="Account is deactivated.")

    access_token, refresh_token = await _create_session_and_cookie(user, request, response, db)
    await _safe_audit_auth(
        db,
        action="auth_login",
        actor=user.username,
        tool_input={"username": user.username, "role": user.role.value},
    )
    return _login_response(user, access_token, refresh_token)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    actor = "anonymous"
    access_token = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME)
    if access_token:
        try:
            payload = decode_token(access_token)
            actor = payload.get("username") or payload.get("sub") or actor
        except Exception:
            actor = "expired_session"
    await _safe_audit_auth(db, action="auth_logout", actor=actor)
    _clear_access_cookie(response)
    return None


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(payload: RefreshRequest, response: Response, db: AsyncSession = Depends(get_db)):
    token_data = decode_token(payload.refresh_token)
    if token_data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token.")

    result = await db.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(UserSession.refresh_token == payload.refresh_token)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=401, detail="Refresh session not found.")

    session, user = row
    if not user.is_active or token_data.get("user_version", 0) != user.token_version:
        raise HTTPException(status_code=401, detail="Account inactive or session revoked. Sign in again.")
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if session.is_revoked or expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Refresh token expired or revoked.")

    session.is_revoked = True

    access_token = create_access_token(data=_token_payload(user))
    refresh_token = create_refresh_token(data=_token_payload(user))
    refresh_payload = decode_token(refresh_token)

    db.add(
        UserSession(
            user_id=str(user.id),
            refresh_token=refresh_token,
            expires_at=datetime.fromtimestamp(refresh_payload["exp"], tz=timezone.utc),
            is_revoked=False,
        )
    )
    await db.flush()
    _set_access_cookie(response, access_token)
    await _safe_audit_auth(
        db,
        action="auth_refresh",
        actor=user.username,
        tool_input={"username": user.username, "role": user.role.value},
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user_id=str(user.id),
        username=user.username,
        role=user.role.value,
    )


@router.get("/me", response_model=UserOut)
async def get_current_user_info(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if auth_bypass_enabled() or current_user.get("is_desktop_user"):
        return {
            "id": "desktop_user",
            "email": "desktop@local.app",
            "username": "desktop_user",
            "role": UserRole.ADMIN.value,
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
        }
    user = await db.get(User, current_user["sub"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


@router.post("/users/{user_id}/status-requests", response_model=UserStatusApprovalOut, status_code=202)
async def request_user_status_change(
    user_id: UUID,
    payload: UserStatusChangeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("users:manage")),
):
    """Prepare an admin-only account change; the separate approval decision applies it."""
    user = await validate_status_change(db, str(user_id), payload.is_active, current_user)
    action = "Activate" if payload.is_active else "Deactivate"
    actor = current_user.get("username") or current_user.get("sub") or "unknown"
    approval = await create_approval_request(
        db=db, session_id=f"user-status:{user.id}", requested_by=actor,
        tool_name="admin_set_user_active",
        tool_input={"user_id": user.id, "username": user.username, "is_active": payload.is_active,
                    "expected_account_revision": user.token_version},
        action=f"{action} account", risk_level="high",
        summary=f"{action} {user.username} ({user.role.value}).",
        timeout_seconds=settings.HITL_APPROVAL_TIMEOUT_SECONDS,
    )
    await audit_service.log_execution(
        db, tool_name="admin_set_user_active", action_summary=f"Requested: {action.lower()} {user.username}.",
        status="pending", actor=actor,
        tool_input={"user_id": user.id, "is_active": payload.is_active, "approval_id": approval.id},
    )
    return UserStatusApprovalOut(
        approval_id=UUID(approval.id), user=UserOut.model_validate(user), is_active=payload.is_active
    )


@router.get("/users", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("users:manage")),
):
    """Admin-only user directory."""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    payload: AdminCreateUser,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("users:manage")),
):
    """Admin-only provisioning of developer accounts."""
    role = coerce_role(payload.role)
    user = await _create_user_record(
        db,
        email=str(payload.email),
        username=payload.username,
        password=payload.password,
        role=role,
        is_active=payload.is_active,
    )
    await _safe_audit_auth(
        db,
        action="auth_admin_create_user",
        actor=current_user.get("username") or current_user.get("sub") or "unknown",
        tool_input={"username": user.username, "role": user.role.value, "is_active": user.is_active},
    )
    return user
