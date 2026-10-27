"""Tests for safe fix pull request generation."""
from __future__ import annotations

import json

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.models import ApprovalRequest, Execution, RepositoryInstallation
from app.services import fix_pr_service
from app.services.workflow_failure_service import create_workflow_failure
from app.tools.github_tool import GitHubToolError


TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = async_sessionmaker(test_engine, expire_on_commit=False)


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


async def _failure(db_session: AsyncSession, *, label: str):
    return await create_workflow_failure(
        db_session,
        repo_full_name="octo-org/demo-app",
        workflow_run_id=987654321,
        workflow_name="CI",
        branch="feature/demo",
        conclusion="failure",
        workflow_url="https://github.com/octo-org/demo-app/actions/runs/987654321",
        log_excerpt="CI failed",
        predicted_label=label,
        confidence=0.91,
        suggested_fix="Use a safe workflow fix.",
        recommendation={
            "summary": "Demo recommendation",
            "root_cause": "Demo root cause",
            "safe_fix_available": label != "wrong_runtime_version",
            "recommended_changes": ["Review workflow file."],
            "risk_level": "low" if label != "wrong_runtime_version" else "medium",
            "requires_approval": label == "wrong_runtime_version",
        },
        status="diagnosed",
    )


@pytest.mark.asyncio
async def test_create_fix_pr_for_npm_missing_test_script(monkeypatch, db_session: AsyncSession):
    failure = await _failure(db_session, label="npm_missing_test_script")
    calls: dict[str, object] = {}

    monkeypatch.setattr(fix_pr_service.github_tool, "get_default_branch", lambda repo: "main")

    def _get_file_content(repo_full_name: str, path: str, branch: str):
        assert repo_full_name == "octo-org/demo-app"
        assert branch == "main"
        if path != ".github/workflows/ci.yml":
            raise GitHubToolError("Unable to read file: repository or resource not found.")
        return {
            "path": path,
            "branch": branch,
            "content": "name: CI\njobs:\n  test:\n    steps:\n      - run: npm test\n",
            "sha": "workflow-sha",
        }

    def _create_branch(repo_full_name: str, base_branch: str, new_branch: str):
        calls["branch"] = new_branch
        assert base_branch == "main"
        return {"branch": new_branch, "sha": "branch-sha"}

    def _create_or_update_file(
        repo_full_name: str,
        branch: str,
        path: str,
        content: str,
        commit_message: str,
        **kwargs,
    ):
        calls["content"] = content
        calls["workflow_path"] = path
        assert kwargs["overwrite"] is True
        assert branch == "ai-cicd/fix-987654321"
        assert "npm test --if-present" in content
        return {"path": path, "sha": "updated-sha", "action": "updated"}

    def _create_pull_request(repo_full_name: str, head_branch: str, base_branch: str, title: str, body: str):
        calls["pr_body"] = body
        assert head_branch == "ai-cicd/fix-987654321"
        assert base_branch == "main"
        assert "No direct commit was made to main/master." in body
        return {"number": 12, "html_url": "https://github.com/octo-org/demo-app/pull/12"}

    monkeypatch.setattr(fix_pr_service.github_tool, "get_file_content", _get_file_content)
    monkeypatch.setattr(fix_pr_service.github_tool, "create_branch", _create_branch)
    monkeypatch.setattr(fix_pr_service.github_tool, "create_or_update_file", _create_or_update_file)
    monkeypatch.setattr(fix_pr_service.github_tool, "create_pull_request", _create_pull_request)

    result = await fix_pr_service.create_fix_pr_for_failure(
        db_session,
        failure.id,
        {"username": "admin", "role": "admin"},
        bypass_approval=True,
    )

    assert result["status"] == "fix_pr_created"
    assert result["branch"] == "ai-cicd/fix-987654321"
    assert result["workflow_path"] == ".github/workflows/ci.yml"
    assert result["pull_request_url"] == "https://github.com/octo-org/demo-app/pull/12"
    assert failure.fix_pr_url == "https://github.com/octo-org/demo-app/pull/12"
    assert failure.status == "fix_pr_created"
    assert calls["branch"] == "ai-cicd/fix-987654321"

    audit_result = await db_session.execute(select(Execution).where(Execution.tool_name == "github_create_fix_pr"))
    audit = audit_result.scalar_one()
    assert audit.status == "completed"
    assert audit.requested_by == "admin"
    assert json.loads(audit.details)["result"]["status"] == "fix_pr_created"


@pytest.mark.asyncio
async def test_create_fix_pr_uses_installation_token_when_installed(monkeypatch, db_session: AsyncSession):
    failure = await _failure(db_session, label="npm_missing_test_script")
    db_session.add(
        RepositoryInstallation(
            installation_id=202,
            repo_full_name="octo-org/demo-app",
            owner="octo-org",
            repo="demo-app",
            default_branch="main",
            status="active",
        )
    )
    await db_session.flush()

    monkeypatch.setattr(fix_pr_service, "get_installation_access_token", lambda installation_id: "installation-token")

    def _get_default_branch(repo_full_name: str, *, token: str | None = None) -> str:
        assert repo_full_name == "octo-org/demo-app"
        assert token == "installation-token"
        return "main"

    def _get_file_content(repo_full_name: str, path: str, branch: str, *, token: str | None = None):
        assert token == "installation-token"
        if path != ".github/workflows/ci.yml":
            raise GitHubToolError("Unable to read file: repository or resource not found.")
        return {
            "path": path,
            "branch": branch,
            "content": "name: CI\njobs:\n  test:\n    steps:\n      - run: npm test\n",
            "sha": "workflow-sha",
        }

    def _create_branch(
        repo_full_name: str,
        base_branch: str,
        new_branch: str,
        *,
        token: str | None = None,
    ):
        assert token == "installation-token"
        return {"branch": new_branch, "sha": "branch-sha"}

    def _create_or_update_file(
        repo_full_name: str,
        branch: str,
        path: str,
        content: str,
        commit_message: str,
        **kwargs,
    ):
        assert kwargs["token"] == "installation-token"
        assert kwargs["overwrite"] is True
        return {"path": path, "sha": "updated-sha", "action": "updated"}

    def _create_pull_request(
        repo_full_name: str,
        head_branch: str,
        base_branch: str,
        title: str,
        body: str,
        *,
        token: str | None = None,
    ):
        assert token == "installation-token"
        return {"number": 12, "html_url": "https://github.com/octo-org/demo-app/pull/12"}

    monkeypatch.setattr(fix_pr_service.github_tool, "get_default_branch", _get_default_branch)
    monkeypatch.setattr(fix_pr_service.github_tool, "get_file_content", _get_file_content)
    monkeypatch.setattr(fix_pr_service.github_tool, "create_branch", _create_branch)
    monkeypatch.setattr(fix_pr_service.github_tool, "create_or_update_file", _create_or_update_file)
    monkeypatch.setattr(fix_pr_service.github_tool, "create_pull_request", _create_pull_request)

    result = await fix_pr_service.create_fix_pr_for_failure(
        db_session,
        failure.id,
        {"username": "admin", "role": "admin"},
        bypass_approval=True,
    )

    assert result["status"] == "fix_pr_created"
    assert result["auth_mode"] == "github_app_installation"
    assert result["installation_id"] == 202

    audit_result = await db_session.execute(select(Execution).where(Execution.tool_name == "github_create_fix_pr"))
    audit = audit_result.scalar_one()
    audit_details = json.loads(audit.details)
    assert audit_details["result"]["auth_mode"] == "github_app_installation"


@pytest.mark.asyncio
async def test_create_fix_pr_for_pytest_not_found_adds_install_step(monkeypatch, db_session: AsyncSession):
    failure = await _failure(db_session, label="pytest_not_found")
    captured: dict[str, str] = {}

    monkeypatch.setattr(fix_pr_service.github_tool, "get_default_branch", lambda repo: "main")
    monkeypatch.setattr(
        fix_pr_service.github_tool,
        "get_file_content",
        lambda repo, path, branch: {
            "path": ".github/workflows/ci.yml",
            "branch": "main",
            "content": "name: CI\njobs:\n  test:\n    steps:\n      - run: pytest\n",
            "sha": "workflow-sha",
        },
    )
    monkeypatch.setattr(
        fix_pr_service.github_tool,
        "create_branch",
        lambda repo, base, branch: {"branch": branch, "sha": "branch-sha"},
    )

    def _update(repo_full_name: str, branch: str, path: str, content: str, commit_message: str, **kwargs):
        captured["content"] = content
        return {"path": path, "sha": "updated-sha", "action": "updated"}

    monkeypatch.setattr(fix_pr_service.github_tool, "create_or_update_file", _update)
    monkeypatch.setattr(
        fix_pr_service.github_tool,
        "create_pull_request",
        lambda repo, head, base, title, body: {
            "number": 13,
            "html_url": "https://github.com/octo-org/demo-app/pull/13",
        },
    )

    result = await fix_pr_service.create_fix_pr_for_failure(db_session, failure.id, bypass_approval=True)

    assert result["status"] == "fix_pr_created"
    assert "python -m pip install pytest" in captured["content"]
    assert "pytest" in captured["content"]


@pytest.mark.asyncio
async def test_wrong_runtime_version_creates_pending_approval(monkeypatch, db_session: AsyncSession):
    failure = await _failure(db_session, label="wrong_runtime_version")

    def _unexpected_write(*args, **kwargs):
        raise AssertionError("GitHub writes should not be called for medium-risk runtime fixes.")

    monkeypatch.setattr(fix_pr_service.github_tool, "create_branch", _unexpected_write)
    monkeypatch.setattr(fix_pr_service.github_tool, "create_or_update_file", _unexpected_write)
    monkeypatch.setattr(fix_pr_service.github_tool, "create_pull_request", _unexpected_write)

    result = await fix_pr_service.create_fix_pr_for_failure(db_session, failure.id)

    assert result["status"] == "approval_required"
    assert result["approval_id"]
    assert result["pull_request_url"] is None
    assert result["recommendation"]["requires_approval"] is True
    assert failure.fix_pr_url is None
    assert failure.status == "approval_pending"

    approval_result = await db_session.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == result["approval_id"])
    )
    approval = approval_result.scalar_one()
    assert approval.status == "pending"
    assert approval.tool_name == "github_create_fix_pr"
    assert approval.risk_level == "medium"
    details = json.loads(approval.tool_input)["approval_details"]
    assert details["repository"] == "octo-org/demo-app"
    assert details["workflow_run_id"] == 987654321
    assert details["predicted_failure"] == "wrong_runtime_version"
    assert details["risk_level"] == "medium"


@pytest.mark.asyncio
async def test_missing_safe_pattern_returns_recommendation_only(monkeypatch, db_session: AsyncSession):
    failure = await _failure(db_session, label="npm_missing_lockfile")

    monkeypatch.setattr(fix_pr_service.github_tool, "get_default_branch", lambda repo: "main")
    monkeypatch.setattr(
        fix_pr_service.github_tool,
        "get_file_content",
        lambda repo, path, branch: {
            "path": ".github/workflows/ci.yml",
            "branch": "main",
            "content": "name: CI\njobs:\n  test:\n    steps:\n      - run: npm install\n",
            "sha": "workflow-sha",
        },
    )

    result = await fix_pr_service.create_fix_pr_for_failure(db_session, failure.id, bypass_approval=True)

    assert result["status"] == "recommendation_only"
    assert result["workflow_path"] == ".github/workflows/ci.yml"
    assert "safe, recognizable pattern" in result["message"]


@pytest.mark.asyncio
async def test_low_risk_fix_requires_approval_even_when_demo_gates_disabled(monkeypatch, db_session):
    from app.core.config import settings
    monkeypatch.setattr(settings, "ENABLE_HITL", False)
    failure = await _failure(db_session, label="npm_missing_test_script")

    def unexpected(*args, **kwargs):
        raise AssertionError("No GitHub reads or writes before explicit approval")
    monkeypatch.setattr(fix_pr_service.github_tool, "get_default_branch", unexpected)
    monkeypatch.setattr(fix_pr_service.github_tool, "create_branch", unexpected)
    response = await fix_pr_service.create_fix_pr_for_failure(db_session, failure.id, {"username": "alice"})
    assert response["status"] == "approval_required"
    approval = await db_session.get(ApprovalRequest, response["approval_id"])
    assert approval.status == "pending" and approval.expires_at is not None
