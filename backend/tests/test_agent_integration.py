"""
Integration tests covering all 6 improvements:

1. HITL approval flow (create → list → decide → audit)
2. Persistent DB-backed memory across simulated restarts
3. Intent-routing removed — agent always invoked for unknown queries
4. Rate-limiting: per-user WS connection limit
5. WebSocket streaming + heartbeat
6. Execution audit trail written for every chat turn
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.core.security import create_access_token

pytestmark = pytest.mark.usefixtures("isolated_app_database")

# ── In-memory SQLite test DB ──────────────────────────────────────────────────

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = async_sessionmaker(test_engine, expire_on_commit=False)


# ── Minimal test app ──────────────────────────────────────────────────────────

def _build_test_app() -> FastAPI:
    from app.api.routes import agent as agent_router, approvals, executions, health

    _app = FastAPI(title="Test")
    _app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    _app.include_router(health.router)
    _app.include_router(agent_router.router, prefix="/api/v1/agent")
    _app.include_router(agent_router.router, prefix="/ws")
    _app.include_router(approvals.router,    prefix="/api/v1/approvals")
    _app.include_router(executions.router,   prefix="/api/v1/executions")
    return _app


_test_app = _build_test_app()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture()
async def db_session():
    async with TestSession() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(autouse=True)
async def override_db(db_session: AsyncSession):
    async def _override():
        yield db_session
    _test_app.dependency_overrides[get_db] = _override
    yield
    _test_app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def client():
    with TestClient(_test_app, raise_server_exceptions=False) as c:
        yield c


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _token(role: str = "developer") -> str:
    return create_access_token({"sub": str(uuid.uuid4()), "role": role, "username": f"user_{role}"})


def _auth(role: str = "developer") -> dict:
    return {"Authorization": f"Bearer {_token(role)}"}


# ── Mock agent factory ────────────────────────────────────────────────────────

def _make_mock_agent(responses: list[str]):
    call_idx = {"n": 0}
    recorded: list[str] = []

    async def _chat(msg: str, db=None) -> dict:
        recorded.append(msg)
        idx = min(call_idx["n"], len(responses) - 1)
        call_idx["n"] += 1
        return {"output": responses[idx], "intermediate_steps": [], "session_id": "mock"}

    mock = MagicMock()
    mock.chat = _chat
    mock.recorded = recorded
    return mock


# ═══════════════════════════════════════════════════════════════════════════════
# 1. HITL Approval flow
# ═══════════════════════════════════════════════════════════════════════════════

class TestHITLApprovalFlow:

    @pytest.mark.asyncio
    async def test_create_approval_request(self, db_session: AsyncSession):
        """Persisting an ApprovalRequest writes a pending row."""
        from app.services.hitl_service import create_approval_request, list_pending

        req = await create_approval_request(
            db_session,
            requested_by="alice",
            action="docker_stop_container",
            risk_level="high",
            summary="Stop nginx container in production",
            payload={"container_name": "nginx"},
        )
        await db_session.commit()

        pending = await list_pending(db_session)
        assert any(r.id == req.id for r in pending)
        assert req.status == "pending"
        assert req.risk_level == "high"

    @pytest.mark.asyncio
    async def test_approve_request(self, db_session: AsyncSession):
        from app.services.hitl_service import create_approval_request, decide_approval, get_payload

        req = await create_approval_request(
            db_session,
            requested_by="bob",
            action="trigger_workflow",
            risk_level="critical",
            summary="Deploy to prod via GitHub Actions",
            payload={"workflow_id": "deploy.yml", "ref": "main"},
        )
        await db_session.commit()

        decided = await decide_approval(
            db_session,
            approval_id=req.id,
            approved=True,
            decided_by="admin",
            note="LGTM",
        )
        await db_session.commit()

        assert decided.status == "approved"
        assert decided.decided_by == "admin"
        payload = get_payload(decided)
        assert payload["workflow_id"] == "deploy.yml"

    @pytest.mark.asyncio
    async def test_reject_request(self, db_session: AsyncSession):
        from app.services.hitl_service import create_approval_request, decide_approval

        req = await create_approval_request(
            db_session,
            requested_by="carol",
            action="docker_stop_container",
            risk_level="high",
            summary="Stop prod DB",
        )
        await db_session.commit()

        decided = await decide_approval(
            db_session, approval_id=req.id,
            approved=False, decided_by="admin", note="Too risky"
        )
        assert decided.status == "rejected"

    @pytest.mark.asyncio
    async def test_double_decide_raises_409(self, db_session: AsyncSession):
        from fastapi import HTTPException
        from app.services.hitl_service import create_approval_request, decide_approval

        req = await create_approval_request(
            db_session, requested_by="dave",
            action="rm_rf", risk_level="critical", summary="bad idea",
        )
        await db_session.commit()
        await decide_approval(db_session, approval_id=req.id, approved=True, decided_by="admin")
        await db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            await decide_approval(db_session, approval_id=req.id, approved=False, decided_by="admin")
        assert exc_info.value.status_code == 409

    def test_list_pending_endpoint_requires_auth(self, client: TestClient):
        resp = client.get("/api/v1/approvals/")
        assert resp.status_code in (401, 403)

    def test_list_pending_endpoint_returns_200(self, client: TestClient):
        resp = client.get("/api/v1/approvals/", headers=_auth("developer"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_developer_decide_endpoint_hides_unknown_requests(self, client: TestClient):
        """An unknown or unowned approval must not be available to a developer."""
        fake_id = str(uuid.uuid4())
        resp = client.post(
            f"/api/v1/approvals/{fake_id}/decide",
            json={"approved": True},
            headers=_auth("developer"),
        )
        assert resp.status_code == 404

    def test_decide_endpoint_404_for_unknown_id(self, client: TestClient):
        fake_id = str(uuid.uuid4())
        resp = client.post(
            f"/api/v1/approvals/{fake_id}/decide",
            json={"approved": True},
            headers=_auth("admin"),
        )
        assert resp.status_code == 404

    def test_chat_hitl_exception_creates_pending_approval(self, client: TestClient):
        from app.agents.tools_registry import HITLApprovalRequired

        class _ApprovalAgent:
            async def chat(self, msg: str, db=None) -> dict:
                raise HITLApprovalRequired(
                    tool_name="github_trigger_workflow",
                    tool_input={"repo_full_name": "octo-org/demo-app", "workflow_id": "deploy.yml", "ref": "main"},
                    risk_level="critical",
                    summary="Trigger production deployment workflow",
                )

        with patch("app.api.routes.agent.get_or_create_agent", return_value=_ApprovalAgent()):
            response = client.post(
                "/api/v1/agent/chat",
                json={"message": "deploy production"},
                headers=_auth("admin"),
            )

        assert response.status_code == 200
        body = response.json()
        assert body["requires_approval"] is True
        assert body["approval_id"]
        assert "Approval required" in body["output"]

        approvals_response = client.get("/api/v1/approvals/", headers=_auth("admin"))
        assert approvals_response.status_code == 200
        approvals = approvals_response.json()
        assert any(item["id"] == body["approval_id"] and item["status"] == "pending" for item in approvals)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Persistent DB-backed memory
# ═══════════════════════════════════════════════════════════════════════════════

class TestPersistentMemory:

    @pytest.mark.asyncio
    async def test_messages_survive_agent_pool_clear(self, db_session: AsyncSession):
        """
        Simulate a server restart by clearing the in-process agent pool
        and verify that chat history is still loaded from DB on the next call.
        """
        from app.services.memory_service import DBChatMessageHistory

        sid = str(uuid.uuid4())
        history = DBChatMessageHistory(session_id=sid, db=db_session)

        # Write 3 turns directly to DB
        await history.aadd_messages("turn 1 human", "turn 1 ai")
        await history.aadd_messages("turn 2 human", "turn 2 ai")
        await history.aadd_messages("turn 3 human", "turn 3 ai")
        await db_session.commit()

        # Clear the in-process pool (simulates restart)
        from app.agents.devops_agent import _agent_pool
        _agent_pool.clear()

        # Reload messages — must still be there
        reloaded = await history.aget_messages()
        assert len(reloaded) == 6  # 3 human + 3 ai

    @pytest.mark.asyncio
    async def test_memory_window_caps_at_k(self, db_session: AsyncSession):
        """Messages beyond k=20 are not returned."""
        from app.services.memory_service import DBChatMessageHistory, MEMORY_WINDOW_K

        sid = str(uuid.uuid4())
        history = DBChatMessageHistory(session_id=sid, db=db_session)

        # Write more than k turns
        for i in range(MEMORY_WINDOW_K + 5):
            await history.aadd_messages(f"human {i}", f"ai {i}")
        await db_session.commit()

        msgs = await history.aget_messages(limit=MEMORY_WINDOW_K)
        assert len(msgs) == MEMORY_WINDOW_K

    @pytest.mark.asyncio
    async def test_clear_deletes_messages(self, db_session: AsyncSession):
        from app.services.memory_service import DBChatMessageHistory

        sid = str(uuid.uuid4())
        history = DBChatMessageHistory(session_id=sid, db=db_session)
        await history.aadd_messages("hello", "world")
        await db_session.commit()

        await history.aclear()
        await db_session.commit()

        msgs = await history.aget_messages()
        assert msgs == []

    @pytest.mark.asyncio
    async def test_delete_session_endpoint_clears_db(self, db_session: AsyncSession, client: TestClient):
        from app.services.memory_service import DBChatMessageHistory
        from app.api.routes.agent import _scoped_chat_session
        from app.core.security import decode_token

        sid = str(uuid.uuid4())
        auth_headers = _auth()
        payload = decode_token(auth_headers["Authorization"].split(" ", 1)[1])
        history = DBChatMessageHistory(session_id=_scoped_chat_session(sid, payload), db=db_session)
        await history.aadd_messages("will be deleted", "yes")
        await db_session.commit()

        resp = client.delete(f"/api/v1/agent/session/{sid}", headers=auth_headers)
        assert resp.status_code == 204

        # Verify DB cleared (reload via same session)
        remaining = await history.aget_messages()
        assert remaining == []


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Intent routing removed — agent always invoked
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoIntentRouting:

    def test_system_metrics_goes_through_agent(self, client: TestClient):
        """
        Previously 'show CPU usage' bypassed the agent. Now it must reach
        get_or_create_agent() so the LLM + tools decides what to do.
        """
        with patch("app.api.routes.agent.get_or_create_agent") as mock_factory:
            mock_factory.return_value = _make_mock_agent(["CPU is at 42%"])
            resp = client.post(
                "/api/v1/agent/chat",
                json={"message": "show me CPU usage"},
                headers=_auth(),
            )
        assert resp.status_code == 200
        # The factory must have been called (agent was invoked)
        mock_factory.assert_called_once()

    def test_docker_list_goes_through_agent(self, client: TestClient):
        with patch("app.api.routes.agent.get_or_create_agent") as mock_factory:
            mock_factory.return_value = _make_mock_agent(["nginx, redis running"])
            resp = client.post(
                "/api/v1/agent/chat",
                json={"message": "list running docker containers"},
                headers=_auth(),
            )
        assert resp.status_code == 200
        mock_factory.assert_called_once()

    def test_arbitrary_question_goes_through_agent(self, client: TestClient):
        with patch("app.api.routes.agent.get_or_create_agent") as mock_factory:
            mock_factory.return_value = _make_mock_agent(["I can help with DevOps tasks"])
            resp = client.post(
                "/api/v1/agent/chat",
                json={"message": "what can you help me with?"},
                headers=_auth(),
            )
        assert resp.status_code == 200
        mock_factory.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. WebSocket connection limit
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebSocketConnectionLimit:

    @pytest.mark.asyncio
    async def test_manager_connect_and_disconnect(self):
        from app.services.ws_manager import ConnectionManager

        mgr = ConnectionManager()
        user_id = str(uuid.uuid4())

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.close = AsyncMock()

        result = await mgr.connect(ws, user_id)
        assert result is True
        assert mgr.active_count(user_id) == 1

        await mgr.disconnect(ws, user_id)
        assert mgr.active_count(user_id) == 0

    @pytest.mark.asyncio
    async def test_per_user_limit_enforced(self):
        from app.services.ws_manager import ConnectionManager, MAX_CONNECTIONS_PER_USER

        mgr = ConnectionManager()
        user_id = str(uuid.uuid4())

        async def _mock_ws():
            ws = MagicMock()
            ws.accept = AsyncMock()
            ws.close = AsyncMock()
            return ws

        # Fill up to the limit
        sockets = []
        for _ in range(MAX_CONNECTIONS_PER_USER):
            ws = await _mock_ws()
            ok = await mgr.connect(ws, user_id)
            assert ok is True
            sockets.append(ws)

        # One more should be rejected
        overflow = await _mock_ws()
        ok = await mgr.connect(overflow, user_id)
        assert ok is False
        overflow.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_total_connections_counter(self):
        from app.services.ws_manager import ConnectionManager

        mgr = ConnectionManager()
        assert mgr.total_connections() == 0

        for user_id in ["u1", "u2", "u3"]:
            ws = MagicMock()
            ws.accept = AsyncMock()
            ws.close = AsyncMock()
            await mgr.connect(ws, user_id)

        assert mgr.total_connections() == 3


# ═══════════════════════════════════════════════════════════════════════════════
# 5. WebSocket streaming
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebSocketStreaming:

    def test_ws_rejects_missing_token(self):
        with TestClient(_test_app) as c:
            with pytest.raises(Exception):
                with c.websocket_connect("/ws/ws/agent") as ws:
                    ws.receive_text()

    def test_ws_rejects_bad_token(self):
        with TestClient(_test_app) as c:
            with pytest.raises(Exception):
                with c.websocket_connect("/ws/ws/agent?token=garbage") as ws:
                    ws.receive_text()

    @pytest.mark.asyncio
    async def test_ws_streams_tokens_and_done_event(self):
        token = _token("developer")
        sid = str(uuid.uuid4())

        async def _fake_stream(msg: str, db=None):
            for chunk in ["Hello", " world", "!"]:
                yield chunk

        mock_agent = MagicMock()
        mock_agent.stream_chat = _fake_stream

        with patch("app.api.routes.agent.get_or_create_agent", return_value=mock_agent):
            with TestClient(_test_app) as c:
                with c.websocket_connect(f"/ws/ws/agent?token={token}") as ws:
                    ws.send_json({"message": "hello", "session_id": sid})

                    collected, done_event = [], None
                    for _ in range(20):
                        raw = ws.receive_text()
                        try:
                            frame = json.loads(raw)
                            if isinstance(frame, dict) and frame.get("event") == "error":
                                pytest.fail("WebSocket streaming returned an error frame.", pytrace=False)
                            if isinstance(frame, dict) and frame.get("event") == "done":
                                done_event = frame
                                break
                        except json.JSONDecodeError:
                            collected.append(raw)

        assert "".join(collected) == "Hello world!"
        assert done_event is not None
        assert done_event["event"] == "done"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Execution audit trail
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecutionAuditTrail:

    @pytest.mark.asyncio
    async def test_execution_created_and_completed(self, db_session: AsyncSession):
        from app.services.execution_service import create_execution, complete_execution
        from sqlalchemy import select
        from app.models.models import Execution

        exc = await create_execution(
            db_session, requested_by="eve",
            summary="list docker containers", source="agent"
        )
        await db_session.commit()
        assert exc.status == "running"

        await complete_execution(
            db_session, execution=exc,
            output="nginx running", intermediate_steps=["step1"]
        )
        await db_session.commit()

        result = await db_session.execute(select(Execution).where(Execution.id == exc.id))
        row = result.scalar_one()
        assert row.status == "completed"
        assert row.completed_at is not None
        assert "nginx" in row.summary

    def test_executions_endpoint_returns_list(self, client: TestClient):
        resp = client.get("/api/v1/executions/", headers=_auth("developer"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_executions_endpoint_requires_auth(self, client: TestClient):
        resp = client.get("/api/v1/executions/")
        assert resp.status_code in (401, 403)

    def test_single_execution_404_for_unknown(self, client: TestClient):
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/v1/executions/{fake_id}", headers=_auth("developer"))
        assert resp.status_code == 404

    def test_chat_creates_execution_record(self, client: TestClient):
        """Every POST /chat must result in an Execution row."""
        with patch("app.api.routes.agent.get_or_create_agent") as mock_factory:
            mock_factory.return_value = _make_mock_agent(["done"])
            client.post(
                "/api/v1/agent/chat",
                json={"message": "list containers"},
                headers=_auth(),
            )

        executions_resp = client.get("/api/v1/executions/", headers=_auth())
        assert executions_resp.status_code == 200
        # At least one execution should be present
        assert len(executions_resp.json()) >= 1
