"""Integration tests for the agent HTTP and WebSocket surfaces."""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.main import app

pytestmark = pytest.mark.usefixtures("isolated_app_database")


def _auth_headers(role: str = "admin", username: str = "integration-user") -> dict[str, str]:
    token = create_access_token(
        {
            "sub": f"{username}-{role}",
            "username": username,
            "role": role,
        }
    )
    return {"Authorization": f"Bearer {token}"}


def test_agent_chat_retains_context_across_three_messages(monkeypatch):
    from app.agents.devops_agent import _agent_pool
    from app.core.config import settings

    monkeypatch.setattr(settings, "DEFAULT_LLM_PROVIDER", "test")
    monkeypatch.setattr(settings, "MEMORY_BACKEND", "inmemory")
    session_id = f"chat-it-{uuid.uuid4()}"

    with TestClient(app) as client:
        response_1 = client.post(
            "/api/agent/chat",
            headers=_auth_headers(),
            json={"session_id": session_id, "message": "Hello from the first message."},
        )
        response_2 = client.post(
            "/api/agent/chat",
            headers=_auth_headers(),
            json={"session_id": session_id, "message": "This is my second message."},
        )
        response_3 = client.post(
            "/api/agent/chat",
            headers=_auth_headers(),
            json={"session_id": session_id, "message": "What was my first message?"},
        )

    assert response_1.status_code == 200
    assert response_2.status_code == 200
    assert response_3.status_code == 200
    assert response_3.json()["session_id"] == session_id
    assert "Hello from the first message." in response_3.json()["output"]

    _agent_pool.pop(session_id, None)


def test_agent_orchestrate_routes_running_containers_to_cli_agent(monkeypatch):
    monkeypatch.setattr(
        "app.agents.cli_agent.docker_tool.list_containers",
        lambda: "- [running] api (image: demo-api, ports: 8000->8000/tcp)",
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/agent/orchestrate",
            headers=_auth_headers(),
            json={"message": "show running containers", "context": {}},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["selected_agent"] == "cli_agent"
    assert body["intent"] == "docker_list_containers"
    assert body["risk_level"] == "low"
    assert body["success"] is True
    assert "api" in body["result"]
    assert body["metadata"]["tool_called"] == "list_containers"
    assert body["metadata"]["trace_steps"][0]["actor"] == "User"
    assert body["metadata"]["trace_steps"][1]["actor"] == "Orchestration Agent"
    assert body["metadata"]["trace_steps"][2]["actor"] == "CLI Agent"
    assert body["metadata"]["trace_steps"][3]["actor"] == "Docker Tool"

    with TestClient(app) as client:
        audit_response = client.get(
            "/api/v1/audit",
            headers=_auth_headers(),
            params={"tool": "multi_agent_orchestration", "limit": 5},
        )

    assert audit_response.status_code == 200
    records = audit_response.json()
    assert records
    matching_record = next(
        record for record in records
        if "Routed request to cli_agent for docker_list_containers" in record["summary"]
    )
    details = json.loads(matching_record["details"])
    assert details["input"]["request_received"] is True
    assert details["output"]["selected_agent"] == "cli_agent"
    assert details["output"]["intent"] == "docker_list_containers"
    assert details["output"]["risk_level"] == "low"
    assert details["output"]["tool_or_service_called"] == "list_containers"


def test_agent_orchestrate_calls_audit_service(monkeypatch):
    calls = []

    async def _fake_audit_log(*args, **kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr(
        "app.agents.cli_agent.docker_tool.list_containers",
        lambda: "- [running] api (image: demo-api, ports: 8000->8000/tcp)",
    )
    monkeypatch.setattr("app.api.routes.agent.audit_service.log_multi_agent_execution", _fake_audit_log)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/agent/orchestrate",
            headers=_auth_headers(),
            json={"message": "show running containers", "context": {}},
        )

    assert response.status_code == 200
    assert calls
    assert calls[0]["selected_agent"] == "cli_agent"
    assert calls[0]["intent"] == "docker_list_containers"
    assert calls[0]["risk_level"] == "low"
    assert calls[0]["success"] is True
    assert calls[0]["metadata"]["tool_called"] == "list_containers"


def test_agent_orchestrate_requires_approval_for_workflow_pr(monkeypatch):
    def _fail_if_called(repo_full_name: str):
        raise AssertionError("create_workflow_pr should not run before approval")

    monkeypatch.setattr("app.agents.github_agent.github_tool.create_workflow_pr", _fail_if_called)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/agent/orchestrate",
            headers=_auth_headers(),
            json={
                "message": "create workflow PR",
                "context": {"repo_full_name": "octo-org/demo-app"},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["selected_agent"] == "github_agent"
    assert body["intent"] == "github_create_workflow_pr"
    assert body["risk_level"] == "medium"
    assert body["success"] is False
    assert body["metadata"]["approval_required"] is True
    assert body["metadata"]["approval_id"]
    assert body["metadata"]["proposed_tool_call"] == "github_create_workflow_pr"
    assert body["metadata"]["approval_details"]["repository"] == "octo-org/demo-app"
    assert body["metadata"]["trace_steps"][2]["actor"] == "GitHub Agent"
    assert body["metadata"]["trace_steps"][3]["status"] == "pending"

    with TestClient(app) as client:
        approvals_response = client.get(
            "/api/v1/approvals",
            headers=_auth_headers(role="admin", username="ops"),
        )

    assert approvals_response.status_code == 200
    approval = next(item for item in approvals_response.json() if item["id"] == body["metadata"]["approval_id"])
    assert approval["status"] == "pending"
    assert approval["tool_name"] == "github_create_workflow_pr"
    assert approval["risk_level"] == "medium"


def test_agent_orchestrate_returns_unknown_route():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/agent/orchestrate",
            headers=_auth_headers(),
            json={"message": "explain devops culture", "context": {}},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["selected_agent"] == "orchestration_agent"
    assert body["intent"] == "unknown"
    assert body["risk_level"] == "low"
    assert body["success"] is False
    assert body["result"] == "I could not route this request to a specialized agent."


def test_agent_websocket_streams_tokens(monkeypatch):
    from app.agents.devops_agent import _agent_pool
    from app.core.config import settings

    monkeypatch.setattr(settings, "DEFAULT_LLM_PROVIDER", "test")
    monkeypatch.setattr(settings, "MEMORY_BACKEND", "inmemory")

    token = create_access_token(
        {
            "sub": "ws-user",
            "username": "ws-user",
            "role": "developer",
        }
    )
    session_id = f"ws-it-{uuid.uuid4()}"

    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/agent?token={token}&session_id={session_id}") as websocket:
            websocket.send_json({"message": "Stream this reply.", "session_id": session_id})

            expected = "Test agent received: Stream this reply."
            chunks = []
            for _ in expected:
                chunk = websocket.receive_text()
                try:
                    frame = json.loads(chunk)
                except json.JSONDecodeError:
                    chunks.append(chunk)
                    continue
                if isinstance(frame, dict) and "event" in frame:
                    pytest.fail(f"Expected a text token, received WebSocket {frame['event']} event.", pytrace=False)
                chunks.append(chunk)
            done = websocket.receive_json()

    assert "".join(chunks) == expected
    assert done == {"event": "done", "session_id": session_id}
    _agent_pool.pop(session_id, None)
