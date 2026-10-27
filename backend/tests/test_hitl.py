# backend/tests/test_hitl.py
"""
Integration tests for the HITL approval flow.

Covers:
  1. create_approval_request() persists a pending record
  2. GET /api/v1/approvals/ lists pending records
  3. POST /api/v1/approvals/{id}/decide (approved=True) executes the tool and creates an Execution
  4. POST /api/v1/approvals/{id}/decide (approved=False) cancels and creates a cancelled Execution
  5. Double-deciding an already-decided approval returns 409
  6. HITLApprovalRequired is raised by the tool wrapper when ENABLE_HITL=True
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes import approvals as approvals_router, health
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models.models import ApprovalRequest, RepositoryInstallation, WorkflowFailure


# In-memory SQLite test DB

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = async_sessionmaker(test_engine, expire_on_commit=False)


def _build_approvals_app() -> FastAPI:
    _app = FastAPI(title="HITL Test App")
    _app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    _app.include_router(health.router)
    _app.include_router(approvals_router.router, prefix="/api/v1/approvals", tags=["Approvals"])
    return _app


app = _build_approvals_app()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture()
async def db_session() -> AsyncSession:
    async with TestSession() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(autouse=True)
async def override_db(db_session: AsyncSession):
    async def _override():
        yield db_session
    app.dependency_overrides[get_db] = _override
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture()
async def client() -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _admin_headers() -> dict:
    token = create_access_token({"sub": str(uuid.uuid4()), "role": "admin", "username": "admin"})
    return {"Authorization": f"Bearer {token}"}


def _dev_headers() -> dict:
    token = create_access_token({"sub": str(uuid.uuid4()), "role": "developer", "username": "dev"})
    return {"Authorization": f"Bearer {token}"}


# Helper

async def _seed_approval(db: AsyncSession, status: str = "pending", **overrides) -> ApprovalRequest:
    record = ApprovalRequest(
        id=str(uuid.uuid4()),
        session_id=overrides.get("session_id", "sess-1"),
        requested_by=overrides.get("requested_by", "dev"),
        tool_name=overrides.get("tool_name", "docker_stop_container"),
        tool_input=json.dumps({"container_name": "nginx"}),
        action="Stop nginx container",
        risk_level="high",
        summary="Stop nginx for maintenance",
        status=status,
        expires_at=datetime.now(tz=timezone.utc) + timedelta(minutes=10),
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return record


# Tests

class TestCreateApprovalRequest:
    @pytest.mark.asyncio
    async def test_create_persists_pending_record(self, db_session: AsyncSession):
        from app.api.routes.approvals import create_approval_request

        record = await create_approval_request(
            db=db_session,
            session_id="test-session",
            requested_by="engineer",
            tool_name="docker_stop_container",
            tool_input={"container_name": "app"},
            action="Stop app container",
            risk_level="high",
            summary="Stopping app container for deployment",
        )
        assert record.id is not None
        assert record.status == "pending"
        assert record.tool_name == "docker_stop_container"
        assert record.requested_by == "engineer"


class TestListApprovals:
    @pytest.mark.asyncio
    async def test_list_returns_pending_approvals(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_approval(db_session)
        resp = await client.get("/api/v1/approvals/", headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_list_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/v1/approvals/")
        assert resp.status_code in (401, 403)


class TestDecideApproval:
    @pytest.mark.asyncio
    async def test_approve_calls_tool_and_creates_execution(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        record = await _seed_approval(db_session)

        with patch("app.api.routes.approvals._dispatch_tool", return_value=("✅ Stopped", "completed")):
            resp = await client.post(
                f"/api/v1/approvals/{record.id}/decide",
                json={"approved": True, "note": "Looks good"},
                headers=_admin_headers(),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "approved"
        assert body["execution_status"] == "completed"
        assert "execution_id" in body

        # Reload DB record
        await db_session.refresh(record)
        assert record.status == "approved"

    @pytest.mark.asyncio
    async def test_reject_creates_cancelled_execution(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        record = await _seed_approval(db_session)
        resp = await client.post(
            f"/api/v1/approvals/{record.id}/decide",
            json={"approved": False, "note": "Too risky right now"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "rejected"
        await db_session.refresh(record)
        assert record.status == "rejected"

    @pytest.mark.asyncio
    async def test_approve_fix_pr_approval_resumes_fix_service(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        failure = WorkflowFailure(
            id=str(uuid.uuid4()),
            repo_full_name="octo-org/demo-app",
            workflow_run_id=456,
            workflow_name="CI",
            conclusion="failure",
            predicted_label="wrong_runtime_version",
            suggested_fix="Update the runtime version.",
            status="approval_pending",
        )
        db_session.add(failure)
        record = ApprovalRequest(
            id=str(uuid.uuid4()),
            requested_by="dev",
            tool_name="github_create_fix_pr",
            tool_input=json.dumps({"workflow_failure_id": failure.id}),
            action="Create GitHub fix pull request",
            risk_level="medium",
            summary="Approve fix PR for octo-org/demo-app workflow run 456.",
            status="pending",
        )
        db_session.add(record)
        await db_session.flush()

        async def _fake_create_fix_pr_for_failure(db, workflow_failure_id, current_user, **kwargs):
            assert workflow_failure_id == failure.id
            assert current_user["username"] == "admin"
            assert kwargs["bypass_approval"] is True
            assert kwargs["audit"] is False
            failure.status = "fix_pr_created"
            failure.fix_pr_url = "https://github.com/octo-org/demo-app/pull/456"
            return {
                "workflow_failure_id": failure.id,
                "repo_full_name": failure.repo_full_name,
                "status": "fix_pr_created",
                "pull_request_url": failure.fix_pr_url,
                "message": "Created fix PR after approval.",
            }

        monkeypatch.setattr(approvals_router, "create_fix_pr_for_failure", _fake_create_fix_pr_for_failure)

        resp = await client.post(
            f"/api/v1/approvals/{record.id}/decide",
            json={"approved": True, "note": "Approved for demo"},
            headers=_admin_headers(),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "approved"
        assert body["execution_status"] == "completed"
        await db_session.refresh(record)
        await db_session.refresh(failure)
        assert record.status == "approved"
        assert failure.status == "fix_pr_created"
        assert failure.fix_pr_url == "https://github.com/octo-org/demo-app/pull/456"

    @pytest.mark.asyncio
    async def test_approve_workflow_pr_uses_installation_token(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        db_session.add(
            RepositoryInstallation(
                installation_id=99,
                repo_full_name="octo-org/demo-app",
                owner="octo-org",
                repo="demo-app",
                default_branch="main",
                status="active",
            )
        )
        record = ApprovalRequest(
            id=str(uuid.uuid4()),
            requested_by="dev",
            tool_name="github_create_workflow_pr",
            tool_input=json.dumps(
                {
                    "repo_full_name": "octo-org/demo-app",
                    "overwrite_existing_workflow": True,
                }
            ),
            action="Create GitHub Actions workflow pull request",
            risk_level="medium",
            summary="Approve workflow PR for octo-org/demo-app.",
            status="pending",
        )
        db_session.add(record)
        await db_session.flush()

        monkeypatch.setattr(
            approvals_router,
            "get_installation_access_token",
            lambda installation_id: "installation-token",
        )

        def _fake_create_workflow_pr(
            repo_full_name: str,
            *,
            overwrite_existing_workflow: bool = False,
            token: str | None = None,
        ) -> dict:
            assert repo_full_name == "octo-org/demo-app"
            assert overwrite_existing_workflow is True
            assert token == "installation-token"
            return {
                "repo_full_name": "octo-org/demo-app",
                "branch": "ai-cicd/setup-pipeline",
                "workflow_path": ".github/workflows/ai-generated-ci.yml",
                "pull_request_url": "https://github.com/octo-org/demo-app/pull/7",
            }

        monkeypatch.setattr("app.tools.github_tool.create_workflow_pr", _fake_create_workflow_pr)

        resp = await client.post(
            f"/api/v1/approvals/{record.id}/decide",
            json={"approved": True, "note": "Approved for workflow setup"},
            headers=_admin_headers(),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "approved"
        assert body["execution_status"] == "completed"
        assert "https://github.com/octo-org/demo-app/pull/7" in body["execution_details"]
        assert '"auth_mode": "github_app_installation"' in body["execution_details"]
        await db_session.refresh(record)
        assert record.status == "approved"

    @pytest.mark.asyncio
    async def test_approve_trigger_workflow_uses_installation_token(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        db_session.add(
            RepositoryInstallation(
                installation_id=101,
                repo_full_name="octo-org/demo-app",
                owner="octo-org",
                repo="demo-app",
                default_branch="main",
                status="active",
            )
        )
        record = ApprovalRequest(
            id=str(uuid.uuid4()),
            requested_by="dev",
            tool_name="github_trigger_workflow",
            tool_input=json.dumps(
                {
                    "repo_full_name": "octo-org/demo-app",
                    "workflow_id": "deploy.yml",
                    "ref": "main",
                    "inputs": {"environment": "staging"},
                }
            ),
            action="Trigger GitHub Actions workflow",
            risk_level="medium",
            summary="Approve workflow trigger.",
            status="pending",
        )
        db_session.add(record)
        await db_session.flush()

        monkeypatch.setattr(
            approvals_router,
            "get_installation_access_token",
            lambda installation_id: "installation-token",
        )

        def _fake_trigger_workflow(
            repo_full_name: str,
            workflow_id: str,
            ref: str = "main",
            inputs: dict | None = None,
            *,
            token: str | None = None,
        ) -> str:
            assert repo_full_name == "octo-org/demo-app"
            assert workflow_id == "deploy.yml"
            assert ref == "main"
            assert inputs == {"environment": "staging"}
            assert token == "installation-token"
            return "Workflow triggered"

        monkeypatch.setattr("app.tools.github_tool.trigger_workflow", _fake_trigger_workflow)

        resp = await client.post(
            f"/api/v1/approvals/{record.id}/decide",
            json={"approved": True, "note": "Trigger staging"},
            headers=_admin_headers(),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["execution_status"] == "completed"
        assert '"auth_mode": "github_app_installation"' in body["execution_details"]
        assert '"installation_id": 101' in body["execution_details"]

    @pytest.mark.asyncio
    async def test_approve_fix_pr_approval_creates_pr_with_mocked_github(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        from app.services import fix_pr_service

        failure = WorkflowFailure(
            id=str(uuid.uuid4()),
            repo_full_name="octo-org/demo-app",
            workflow_run_id=321,
            workflow_name="CI",
            conclusion="failure",
            predicted_label="npm_missing_test_script",
            suggested_fix="Use npm test --if-present for repositories without a test script.",
            log_excerpt="npm ERR! Missing script: test",
            status="approval_pending",
        )
        db_session.add(failure)
        record = ApprovalRequest(
            id=str(uuid.uuid4()),
            requested_by="dev",
            tool_name="github_create_fix_pr",
            tool_input=json.dumps({"workflow_failure_id": failure.id}),
            action="Create GitHub fix pull request",
            risk_level="medium",
            summary="Approve fix PR for octo-org/demo-app workflow run 321.",
            status="pending",
        )
        db_session.add(record)
        await db_session.flush()

        captured: dict[str, str] = {}

        async def _no_installation(db, repo_full_name):
            assert repo_full_name == "octo-org/demo-app"
            return None

        def _get_default_branch(repo_full_name: str) -> str:
            assert repo_full_name == "octo-org/demo-app"
            return "main"

        def _get_file_content(repo_full_name: str, path: str, branch: str) -> dict:
            assert repo_full_name == "octo-org/demo-app"
            assert branch == "main"
            assert path == ".github/workflows/ci.yml"
            return {
                "path": path,
                "content": "name: CI\non: [push]\njobs:\n  test:\n    steps:\n      - run: npm test\n",
                "sha": "abc123",
            }

        def _create_branch(repo_full_name: str, base_branch: str, new_branch: str) -> dict:
            captured["branch"] = new_branch
            assert base_branch == "main"
            return {"name": new_branch}

        def _create_or_update_file(
            repo_full_name: str,
            branch: str,
            path: str,
            content: str,
            commit_message: str,
            *,
            overwrite: bool = False,
        ) -> dict:
            captured["content"] = content
            assert branch == "ai-cicd/fix-321"
            assert path == ".github/workflows/ci.yml"
            assert overwrite is True
            assert "npm test --if-present" in content
            return {"path": path, "commit": {"message": commit_message}}

        def _create_pull_request(
            repo_full_name: str,
            head_branch: str,
            base_branch: str,
            title: str,
            body: str,
        ) -> dict:
            captured["pr_body"] = body
            assert head_branch == "ai-cicd/fix-321"
            assert base_branch == "main"
            assert "run 321" in title
            assert "Safety notes" in body
            return {"html_url": "https://github.com/octo-org/demo-app/pull/321"}

        monkeypatch.setattr(fix_pr_service, "get_installation_for_repo", _no_installation)
        monkeypatch.setattr(fix_pr_service.github_tool, "get_default_branch", _get_default_branch)
        monkeypatch.setattr(fix_pr_service.github_tool, "get_file_content", _get_file_content)
        monkeypatch.setattr(fix_pr_service.github_tool, "create_branch", _create_branch)
        monkeypatch.setattr(fix_pr_service.github_tool, "create_or_update_file", _create_or_update_file)
        monkeypatch.setattr(fix_pr_service.github_tool, "create_pull_request", _create_pull_request)

        resp = await client.post(
            f"/api/v1/approvals/{record.id}/decide",
            json={"approved": True, "note": "Approved after review"},
            headers=_admin_headers(),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "approved"
        assert body["execution_status"] == "completed"
        assert "https://github.com/octo-org/demo-app/pull/321" in body["execution_details"]
        assert '"auth_mode": "pat_fallback"' in body["execution_details"]
        await db_session.refresh(record)
        await db_session.refresh(failure)
        assert record.status == "approved"
        assert failure.status == "fix_pr_created"
        assert failure.fix_pr_url == "https://github.com/octo-org/demo-app/pull/321"
        assert captured["branch"] == "ai-cicd/fix-321"
        assert "npm test --if-present" in captured["content"]
        assert "No direct commit was made to main/master" in captured["pr_body"]

    @pytest.mark.asyncio
    async def test_reject_fix_pr_approval_updates_workflow_failure(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        failure = WorkflowFailure(
            id=str(uuid.uuid4()),
            repo_full_name="octo-org/demo-app",
            workflow_run_id=789,
            workflow_name="CI",
            conclusion="failure",
            predicted_label="wrong_runtime_version",
            status="approval_pending",
        )
        db_session.add(failure)
        record = ApprovalRequest(
            id=str(uuid.uuid4()),
            requested_by="dev",
            tool_name="github_create_fix_pr",
            tool_input=json.dumps({"workflow_failure_id": failure.id}),
            action="Create GitHub fix pull request",
            risk_level="medium",
            summary="Approve fix PR for octo-org/demo-app workflow run 789.",
            status="pending",
        )
        db_session.add(record)
        await db_session.flush()

        resp = await client.post(
            f"/api/v1/approvals/{record.id}/decide",
            json={"approved": False, "note": "Needs manual review"},
            headers=_admin_headers(),
        )

        assert resp.status_code == 200
        await db_session.refresh(record)
        await db_session.refresh(failure)
        assert record.status == "rejected"
        assert failure.status == "rejected"

    def test_dispatch_github_write_tools_require_async_dispatcher(self):
        from app.api.routes import approvals as approvals_router

        details, status = approvals_router._dispatch_tool(
            "github_create_workflow_pr",
            {
                "repo_full_name": "octo-org/demo-app",
                "overwrite_existing_workflow": True,
                "approval_details": {"selected_agent": "github_agent"},
            },
        )

        assert status == "failed"
        assert "requires the async approval dispatcher" in details

    @pytest.mark.asyncio
    async def test_decide_twice_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        record = await _seed_approval(db_session, status="approved")
        resp = await client.post(
            f"/api/v1/approvals/{record.id}/decide",
            json={"approved": True},
            headers=_admin_headers(),
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_decide_nonexistent_returns_404(self, client: AsyncClient):
        resp = await client.post(
            f"/api/v1/approvals/{uuid.uuid4()}/decide",
            json={"approved": True},
            headers=_admin_headers(),
        )
        assert resp.status_code == 404


class TestHITLToolWrapper:
    """Unit tests for the HITLApprovalRequired wrapper."""

    def test_hitl_wrap_raises_when_enabled(self):
        from app.agents.tools_registry import HITLApprovalRequired, _hitl_wrap

        def _dummy(container_name: str) -> str:
            return f"stopped {container_name}"

        wrapped = _hitl_wrap(_dummy, "docker_stop_container", "high", "Stop '{container_name}'")

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.ENABLE_HITL = True
            with pytest.raises(HITLApprovalRequired) as exc_info:
                wrapped(container_name="nginx")
            assert exc_info.value.tool_name == "docker_stop_container"
            assert exc_info.value.risk_level == "high"

    def test_hitl_wrap_executes_when_disabled(self):
        from app.agents.tools_registry import _hitl_wrap

        def _dummy(container_name: str) -> str:
            return f"stopped {container_name}"

        wrapped = _hitl_wrap(_dummy, "docker_stop_container", "high", "Stop '{container_name}'")

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.ENABLE_HITL = False
            result = wrapped(container_name="nginx")
            assert result == "stopped nginx"
