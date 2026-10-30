"""Security response policies must hold on successful and rejected requests."""
import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_api_headers_and_private_caching(isolated_app_database):
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for path in ("/api/v1/health", "/api/v1/auth/me", "/api/v1/audit"):
            response = await client.get(path)
            assert response.status_code in {200, 401, 403}
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["x-frame-options"] == "DENY"
            assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
            assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_cors_denials_retain_security_headers(isolated_app_database):
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.options("/api/v1/auth/me", headers={
            "Origin": "https://untrusted.invalid", "Access-Control-Request-Method": "GET",
        })
    assert response.status_code == 400
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_health_does_not_disclose_artifact_directory(isolated_app_database, monkeypatch):
    from app.main import app
    from app.core.config import settings

    monkeypatch.setattr(settings, "FAILURE_MODEL_PATH", "/private/operator/secret-directory/model.joblib")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health/status")
    assert response.status_code == 200
    assert response.json()["ml_model"]["path"] == "model.joblib"
    assert "/private/operator" not in response.text


@pytest.mark.asyncio
async def test_swagger_remains_usable_with_its_document_policy(isolated_app_database):
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/docs")
    assert response.status_code == 200
    assert "SwaggerUIBundle" in response.text
    assert "https://cdn.jsdelivr.net" in response.headers["content-security-policy"]
    assert "unsafe-inline" not in response.headers["content-security-policy"]
    assert '<script nonce="' in response.text


@pytest.mark.asyncio
async def test_html_style_nonce_is_per_response_and_not_cached():
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    from app.core.security_headers import SecurityHeadersMiddleware

    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/")
    def index():
        return HTMLResponse('<meta name="csp-nonce" content="__CSP_NONCE__">')

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first, second = await client.get("/"), await client.get("/")
    nonce = first.text.split('content="')[1].split('"')[0]
    assert f"'nonce-{nonce}'" in first.headers["content-security-policy"]
    assert "unsafe-inline" not in first.headers["content-security-policy"]
    assert first.text != second.text
    assert first.headers["cache-control"] == "no-store"
