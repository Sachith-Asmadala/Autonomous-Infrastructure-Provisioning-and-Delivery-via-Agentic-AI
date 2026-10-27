"""Cookie authentication regression tests for HTTP and HTTPS deployments."""
from http.cookies import SimpleCookie

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import auth
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import ACCESS_TOKEN_COOKIE_NAME, UserRole, hash_password
from app.models.models import User


@pytest_asyncio.fixture
async def auth_client(monkeypatch):
    monkeypatch.setattr(settings, "DESKTOP_MODE", False)
    monkeypatch.setattr(settings, "DISABLE_AUTH", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "COOKIE_SAMESITE", "lax")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        db.add(User(
            email="cookie-test@example.com", username="cookie-test",
            hashed_password=hash_password("cookie-test-password"),
            role=UserRole.DEVELOPER, is_active=True,
        ))
        await db.commit()

    async def override_db():
        async with sessions() as db:
            yield db
            await db.commit()

    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1/auth")
    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            yield client
    finally:
        await engine.dispose()


async def login(client):
    return await client.post("/api/v1/auth/login", json={
        "email": "cookie-test@example.com", "password": "cookie-test-password",
    })


def access_cookie(response):
    cookies = SimpleCookie()
    cookies.load(response.headers["set-cookie"])
    return cookies[ACCESS_TOKEN_COOKIE_NAME]


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["development", "production", "prod", "release"])
@pytest.mark.parametrize("secure", [False, True])
async def test_login_cookie_obeys_explicit_secure_setting(auth_client, monkeypatch, environment, secure):
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    monkeypatch.setattr(settings, "COOKIE_SECURE", secure)

    response = await login(auth_client)

    assert response.status_code == 200
    cookie = access_cookie(response)
    assert bool(cookie["secure"]) is secure
    assert cookie["httponly"]
    assert cookie["samesite"] == "lax"
    assert cookie["path"] == "/"
    assert int(cookie["max-age"]) == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    # The HTTP client must authenticate using only the cookie, without a bearer token.
    me = await auth_client.get("/api/v1/auth/me")
    assert me.status_code == (401 if secure else 200)
    if secure:
        auth_client.base_url = "https://testserver"
        me = await auth_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "cookie-test"
    assert (await auth_client.get("/api/v1/auth/users")).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("secure", [False, True])
async def test_refresh_and_logout_preserve_cookie_security(auth_client, monkeypatch, secure):
    monkeypatch.setattr(settings, "COOKIE_SECURE", secure)
    if secure:
        auth_client.base_url = "https://testserver"
    logged_in = await login(auth_client)
    assert logged_in.status_code == 200
    refreshed = await auth_client.post("/api/v1/auth/refresh", json={
        "refresh_token": logged_in.json()["refresh_token"],
    })
    assert refreshed.status_code == 200
    cookie = access_cookie(refreshed)
    assert bool(cookie["secure"]) is secure
    assert cookie["httponly"]
    assert cookie["samesite"] == "lax"
    assert (await auth_client.get("/api/v1/auth/me")).status_code == 200

    logged_out = await auth_client.post("/api/v1/auth/logout")
    assert logged_out.status_code == 204
    cleared = access_cookie(logged_out)
    assert bool(cleared["secure"]) is secure
    assert cleared["httponly"]
    assert cleared["samesite"] == "lax"
    assert cleared["max-age"] == "0"
    assert (await auth_client.get("/api/v1/auth/me")).status_code == 401
