"""Database connection and session management."""
from __future__ import annotations

import ssl
from typing import Any, AsyncGenerator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import String, cast, or_, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.core.logging import logger


def _normalize_database_url(database_url: str) -> str:
    value = database_url.strip()
    if value.startswith("postgresql+asyncpg://"):
        async_url = value
    elif value.startswith("postgresql://"):
        async_url = value.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif value.startswith("postgres://"):
        async_url = value.replace("postgres://", "postgresql+asyncpg://", 1)
    else:
        async_url = value

    if "pooler.supabase.com" in async_url:
        parts = urlsplit(async_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.setdefault("prepared_statement_cache_size", "0")
        async_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    return async_url


def _connect_args(async_url: str) -> dict[str, Any]:
    if async_url.startswith("sqlite"):
        return {"timeout": 30}
    if async_url.startswith("postgresql+asyncpg"):
        args: dict[str, Any] = {"command_timeout": 60}
        if "supabase.com" in async_url:
            if settings.DATABASE_SSL_VERIFY:
                args["ssl"] = ssl.create_default_context()
            else:
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                args["ssl"] = ssl_context
        if "pooler.supabase.com" in async_url:
            args["statement_cache_size"] = 0
        return args
    return {}


async_url = _normalize_database_url(settings.DATABASE_URL)
connect_args = _connect_args(async_url)

engine = create_async_engine(
    async_url,
    echo=settings.DEBUG,
    future=True,
    hide_parameters=True,
    pool_pre_ping=True,
    connect_args=connect_args,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

try:
    logger.info("database.configured", database_url=make_url(async_url).render_as_string(hide_password=True))
except Exception:
    logger.info("database.configured")


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


async def init_db() -> None:
    """Initialize database tables on startup."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await ensure_schema_compatibility(conn)
            await migrate_retired_roles(conn)
        await ensure_default_admin()
    except Exception as exc:
        logger.warning("database.init.skipped", error=str(exc))


async def ensure_schema_compatibility(conn) -> None:
    """
    Apply small additive schema fixes for demo databases created before newer
    ORM fields existed. Base.metadata.create_all() does not alter existing
    tables, so nullable columns added during MVP development need this shim.
    """
    dialect = conn.dialect.name
    if dialect == "postgresql":
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0"))
        await conn.execute(
            text(
                "ALTER TABLE workflow_failures "
                "ADD COLUMN IF NOT EXISTS recommendation_json TEXT"
            )
        )
        await conn.execute(text("ALTER TABLE workflow_failures ADD COLUMN IF NOT EXISTS requested_by VARCHAR(100)"))
        await conn.execute(text("ALTER TABLE workflow_failures ADD COLUMN IF NOT EXISTS diagnosis_error TEXT"))
        return

    if dialect == "sqlite":
        user_columns = await conn.execute(text("PRAGMA table_info(users)"))
        if "token_version" not in {row[1] for row in user_columns.fetchall()}:
            await conn.execute(text("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"))
        result = await conn.execute(text("PRAGMA table_info(workflow_failures)"))
        columns = {row[1] for row in result.fetchall()}
        if "recommendation_json" not in columns:
            await conn.execute(
                text("ALTER TABLE workflow_failures ADD COLUMN recommendation_json TEXT")
            )
        if "requested_by" not in columns:
            await conn.execute(text("ALTER TABLE workflow_failures ADD COLUMN requested_by VARCHAR(100)"))
        if "diagnosis_error" not in columns:
            await conn.execute(text("ALTER TABLE workflow_failures ADD COLUMN diagnosis_error TEXT"))


async def migrate_retired_roles(conn) -> None:
    """Preserve legacy accounts while moving them to Developer access.

    Cast the stored role before reading it: the current ORM enum intentionally
    cannot deserialize retired values. Revoke both access and refresh sessions
    in the same startup transaction. Repeated startups are a no-op.
    """
    from app.models.models import User, UserSession

    legacy_users = select(User.id).where(cast(User.role, String).in_(["operator", "viewer"]))
    await conn.execute(
        update(UserSession).where(UserSession.user_id.in_(legacy_users)).values(is_revoked=True)
    )
    result = await conn.execute(
        update(User).where(cast(User.role, String).in_(["operator", "viewer"]))
        .values(role="developer", token_version=User.token_version + 1)
    )
    if result.rowcount:
        logger.info("database.roles.migrated", affected_accounts=result.rowcount, target_role="developer")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency: yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def _demo_users() -> list[dict[str, Any]]:
    """Return safe demo RBAC accounts for local/development environments."""
    from app.core.security import UserRole, hash_password

    demo_users = [
        {
            "email": settings.DEFAULT_ADMIN_EMAIL,
            "username": settings.DEFAULT_ADMIN_USERNAME,
            "password": settings.DEFAULT_ADMIN_PASSWORD,
            "role": UserRole.ADMIN,
        },
        {
            "email": "devops.engineer@example.com",
            "username": "devops.engineer",
            "password": "developer123",
            "role": UserRole.DEVELOPER,
        },
    ]

    if settings.ENVIRONMENT.strip().lower() in {"production", "prod", "release"}:
        demo_users = demo_users[:1]

    return [
        {
            **demo,
            "hashed_password": hash_password(demo["password"]),
        }
        for demo in demo_users
    ]


async def ensure_default_users(db: AsyncSession) -> tuple[list[str], list[str]]:
    """Seed default RBAC accounts into the provided session when missing."""
    from app.models.models import User
    from app.core.security import UserRole

    created = []
    updated = []
    for demo in _demo_users():
        legacy_email = demo.get("legacy_email")
        lookup_conditions = [
            User.username == demo["username"],
            User.email == demo["email"],
        ]
        if legacy_email:
            lookup_conditions.append(User.email == legacy_email)

        result = await db.execute(
            select(User).where(or_(*lookup_conditions))
        )
        user = result.scalar_one_or_none()
        if user:
            if legacy_email and user.email == legacy_email:
                user.email = demo["email"]
                updated.append(demo["username"])
            continue

        if demo["role"] == UserRole.ADMIN:
            # Bootstrap the initial administrator only. A changed configured
            # username/email must not create another admin on the next startup.
            existing_admin = await db.scalar(select(User.id).where(User.role == UserRole.ADMIN).limit(1))
            if existing_admin:
                continue

        db.add(
            User(
                email=demo["email"],
                username=demo["username"],
                hashed_password=demo["hashed_password"],
                role=demo["role"],
                is_active=True,
            )
        )
        created.append(demo["username"])

    if created or updated:
        await db.flush()

    return created, updated


async def ensure_default_admin() -> None:
    """Seed safe demo RBAC accounts for local/development environments."""
    async with AsyncSessionLocal() as session:
        created, updated = await ensure_default_users(session)
        if created or updated:
            await session.commit()
            logger.info("database.default_users.seeded", usernames=created, updated_usernames=updated)
