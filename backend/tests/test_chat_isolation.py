"""Account-scoped chat memory, deletion, and safe provider errors."""
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.routes import agent
from app.core.database import get_db
from app.core.security import create_access_token
from app.models.models import ChatMessage
from app.services.memory_service import DBChatMessageHistory


def headers(name):
    token = create_access_token({"sub": name, "username": name, "role": "admin" if name == "admin" else "developer"})
    return {"Authorization": f"Bearer {token}"}


class FakeAgent:
    def __init__(self, session_id, user_role):
        self.session_id = session_id

    async def chat(self, message, db):
        history = DBChatMessageHistory(self.session_id, db)
        previous = await history.aget_messages()
        output = " / ".join([item.content for item in previous] + [message])
        await history.aadd_messages(message, output)
        await db.commit()
        return {"output": output, "session_id": self.session_id, "intermediate_steps": []}

    async def stream_chat(self, message, db):
        result = await self.chat(message, db)
        yield result["output"]


@pytest.mark.asyncio
async def test_http_websocket_and_clear_share_only_this_accounts_memory(isolated_app_database, monkeypatch):
    sessions = isolated_app_database
    monkeypatch.setattr(agent, "get_or_create_agent", FakeAgent)
    app = FastAPI()
    app.include_router(agent.router, prefix="/api/v1/agent")
    app.add_api_websocket_route("/ws/agent", agent.agent_ws)

    async def override_db():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = override_db
    session_id = str(uuid4())
    with TestClient(app) as client:
        for name in ("alice", "bob", "admin"):
            response = client.post("/api/v1/agent/chat", headers=headers(name),
                                   json={"message": name, "session_id": session_id})
            assert response.status_code == 200
            assert response.json()["output"] == name
            assert response.json()["session_id"] == session_id
        with client.websocket_connect("/ws/agent", headers=headers("alice")) as socket:
            socket.send_json({"message": "alice continuation", "session_id": session_id})
            output = socket.receive_text()
            assert "alice" in output and "bob" not in output and "admin" not in output
            assert socket.receive_json()["session_id"] == session_id
        assert client.delete(f"/api/v1/agent/session/{session_id}", headers=headers("bob")).status_code == 204
    async with sessions() as db:
        records = (await db.execute(select(ChatMessage))).scalars().all()
        assert len(records) == 6  # two Alice turns and one Admin turn remain
        assert all(record.content != "bob" for record in records)


@pytest.mark.parametrize("error", [
    "Did not find openai_api_key, please set OPENAI_API_KEY.",
    "The api_key client option must be set.",
])
def test_missing_chat_credentials_are_an_actionable_service_error(error):
    with pytest.raises(HTTPException) as caught:
        agent._raise_provider_errors(ValueError(error))
    assert caught.value.status_code == 503
    assert "Log diagnosis and workflow generation are available" in caught.value.detail


def test_generic_agent_errors_do_not_expose_raw_exception_values():
    with pytest.raises(HTTPException) as caught:
        agent._raise_provider_errors(ValueError("secret-bearing-provider-response"))
    assert "secret-bearing" not in caught.value.detail


@pytest.mark.asyncio
async def test_chat_provider_failure_finishes_its_execution_record(isolated_app_database, monkeypatch):
    from app.models.models import Execution
    sessions = isolated_app_database

    def missing_provider(*args, **kwargs):
        raise ValueError("The api_key client option must be set.")
    monkeypatch.setattr(agent, "get_or_create_agent", missing_provider)
    app = FastAPI()
    app.include_router(agent.router, prefix="/api/v1/agent")
    with TestClient(app) as client:
        response = client.post("/api/v1/agent/chat", headers=headers("alice"), json={"message": "hello"})
        assert response.status_code == 503
    async with sessions() as db:
        record = await db.scalar(select(Execution).where(Execution.requested_by == "alice"))
        assert record.status == "failed" and record.completed_at is not None
        assert record.summary.startswith("AI chat is not configured")
