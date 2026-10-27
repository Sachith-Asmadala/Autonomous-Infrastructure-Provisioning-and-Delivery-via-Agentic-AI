"""Explicit database isolation for tests using the application session factory."""
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


@pytest_asyncio.fixture
async def isolated_app_database(tmp_path, monkeypatch):
    """Give HTTP, startup, and WebSocket code the same disposable database.

    TestClient creates separate event loops. A file-backed SQLite database with
    NullPool retains data across clients without sharing loop-bound connections.
    Modules that already override get_db may continue using their own fixtures.
    """
    from app.api.routes import agent
    from app.core import database
    from app.core.config import settings
    from app.models import models  # noqa: F401 - register every ORM table

    database_url = f"sqlite+aiosqlite:///{tmp_path / 'application-test.db'}"
    engine = create_async_engine(database_url, poolclass=NullPool, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "AsyncSessionLocal", sessions)
    # WebSocket handlers import the factory directly rather than using get_db.
    monkeypatch.setattr(agent, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(settings, "DATABASE_URL", database_url)
    monkeypatch.setattr(settings, "DESKTOP_MODE", False)
    monkeypatch.setattr(settings, "DISABLE_AUTH", False)
    monkeypatch.setattr(settings, "DEFAULT_LLM_PROVIDER", "test")
    monkeypatch.setattr(settings, "MEMORY_BACKEND", "database")
    monkeypatch.setattr(settings, "ENABLE_HITL", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "DEFAULT_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(settings, "DEFAULT_ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "DEFAULT_ADMIN_PASSWORD", "isolated-test-admin-password")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(database.Base.metadata.create_all)
        yield sessions
    finally:
        await engine.dispose()
