"""Controlled auth/security integration supplements unauthenticated passive ZAP."""
import json
import os
import uuid
from pathlib import Path

import pytest
import requests

from qa.security.conftest import login


@pytest.mark.case(
    'SEC-01',
    'Session security',
    'Cookie flags and logout',
    'Cookie is HttpOnly/SameSite and logout invalidates subsequent requests.',
)
def test_cookie_and_logout(api):
    client, base = api
    response = login(client, base)
    cookie = response.headers["Set-Cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get(base + "/api/v1/auth/me", timeout=5).status_code == 200
    assert client.post(base + "/api/v1/auth/logout", timeout=5).status_code == 204
    assert client.get(base + "/api/v1/auth/me", timeout=5).status_code == 401


@pytest.mark.case(
    'SEC-02',
    'RBAC',
    'Anonymous protected API access',
    'Private endpoints reject requests without a session.',
)
@pytest.mark.parametrize("path", ["/auth/me", "/approvals", "/audit", "/evaluation/summary", "/auth/users"])
def test_anonymous_access(api, path):
    client, base = api
    assert client.get(base + "/api/v1" + path, timeout=5).status_code in {401, 403}


@pytest.mark.case(
    'SEC-03',
    'RBAC',
    'Developer cannot escalate role through registration or token claims',
    'Admin endpoints remain forbidden.',
)
def test_developer_cannot_access_administration(api):
    client, base = api
    login(client, base)
    for path in ("/auth/users", "/evaluation/summary"):
        assert client.get(base + "/api/v1" + path, timeout=5).status_code == 403


@pytest.mark.case(
    'SEC-04',
    'CORS',
    'Untrusted cross-origin preflight',
    'Untrusted origins receive no allow-origin permission.',
)
def test_untrusted_cors(api):
    client, base = api
    response = client.options(base + "/api/v1/auth/me", timeout=5, headers={
        "Origin": "https://untrusted.invalid", "Access-Control-Request-Method": "GET"})
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.case(
    'SEC-05',
    'Approvals',
    'Approval ownership and rejected replay',
    'Another account cannot decide; rejection prevents execution and replay.',
)
def test_approval_rejection_and_ownership(api):
    client, base = api
    login(client, base)
    response = client.post(base + "/api/v1/repositories/create-workflow-pr", timeout=5,
                           json={"repo_full_name": "qa/security-" + uuid.uuid4().hex[:8]})
    assert response.status_code == 200
    approval = response.json()
    assert approval["approval_required"] is True and not approval.get("pull_request_url")
    path = base + "/api/v1/approvals/" + approval["approval_id"]
    with requests.Session() as other:
        login(other, base, "qa-other")
        assert other.post(path + "/decide", timeout=5, json={"approved": True}).status_code == 404
    rejected = client.post(path + "/decide", timeout=5, json={"approved": False})
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert client.post(path + "/decide", timeout=5, json={"approved": True}).status_code == 409
    assert client.get(path, timeout=5).json()["status"] == "rejected"


@pytest.mark.case(
    'SEC-06',
    'Approvals',
    'Expired approval API execution gate',
    'Expired request returns 410 and persists timed_out without execution.',
)
def test_expired_approval_execution_is_blocked(api):
    client, base = api
    login(client, base)
    path = base + "/api/v1/approvals/00000000-0000-0000-0000-000000000002"
    before = client.get(path, timeout=5).json()
    assert before["can_approve"] is False
    assert client.post(path + "/decide", timeout=5, json={"approved": True}).status_code == 410
    assert client.get(path, timeout=5).json()["status"] == "timed_out"


@pytest.mark.case(
    'SEC-07',
    'Information disclosure',
    'Audit and account response fields',
    'Responses omit credentials and token-bearing user fields.',
)
def test_private_response_fields(api):
    client, base = api
    login(client, base)
    for path in ("/auth/me", "/audit"):
        response = client.get(base + "/api/v1" + path, timeout=5)
        assert response.status_code == 200
        for field in ("hashed_password", "refresh_token", os.environ["QA_TEST_PASSWORD"]):
            assert field not in response.text
    assert "QA qa-other completed audit record" not in client.get(base + "/api/v1/audit", timeout=5).text


@pytest.mark.case(
    'SEC-08',
    'Security observations',
    'Inventory HTTP headers without suppressing findings',
    'Actual headers and missing protections are recorded for review.',
)
def test_header_inventory(api):
    client, base = api
    login(client, base)
    observations = []
    for path in ("/", "/api/v1/health", "/api/v1/auth/me", "/api/v1/audit"):
        response = client.get(base + path, timeout=5)
        assert response.status_code == 200
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert "frame-ancestors 'none'" in response.headers.get("Content-Security-Policy", "")
        assert response.headers.get("Cache-Control")
        for header, risk, remediation in [
            ("X-Content-Type-Options", "Low", "Send nosniff for API and frontend responses."),
            ("Content-Security-Policy", "Medium", "Define and verify a CSP compatible with the frontend."),
            ("X-Frame-Options", "Medium", "Restrict framing with DENY/SAMEORIGIN or CSP frame-ancestors."),
            ("Cache-Control", "Medium" if path.startswith("/api/v1/auth") else "Low",
             "Use no-store on private authentication responses; define caching per endpoint."),
        ]:
            observations.append({"finding": header, "endpoint": path, "risk": risk,
                                 "evidence": response.headers.get(header, "Header absent"),
                                 "present": header in response.headers, "remediation": remediation,
                                 "false_positive_considerations": "Reverse proxy/TLS is outside this local run.",
                                 "remediation_implemented": header in response.headers,
                                 "source": "Controlled pytest HTTP observation; not ZAP"})
    destination = Path(os.environ["QA_REPORT_DIR"]) / "header-observations.json"
    destination.write_text(json.dumps(observations, indent=2) + "\n")
