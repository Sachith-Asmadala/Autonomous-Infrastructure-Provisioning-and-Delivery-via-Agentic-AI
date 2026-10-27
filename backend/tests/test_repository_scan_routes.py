"""Tests for GitHub repository scan endpoints."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes import approvals, repositories
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models.models import ApprovalRequest, Execution, RepositoryInstallation
from app.tools import github_tool
from app.tools.github_tool import GitHubToolError

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = async_sessionmaker(test_engine, expire_on_commit=False)


def _build_repository_app() -> FastAPI:
    test_app = FastAPI(title="Repository Scan Test App")
    test_app.include_router(repositories.router, prefix="/api/v1/repositories")
    test_app.include_router(approvals.router, prefix="/api/v1/approvals")
    return test_app


app = _build_repository_app()


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


def _auth_headers(role: str = "developer") -> dict[str, str]:
    token = create_access_token(
        {
            "sub": str(uuid.uuid4()),
            "username": "repo-scan-test-user",
            "role": role,
        }
    )
    return {"Authorization": f"Bearer {token}"}


def test_scan_repository_requires_auth():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/repositories/scan",
            json={"repo_full_name": "octo-org/demo-app", "branch": "main"},
        )

    assert response.status_code in (401, 403)


def test_scan_repository_returns_files_and_detected_stack(monkeypatch):
    def _fake_get_repository_analysis_inputs(repo_full_name: str, branch: str | None = None) -> dict[str, list[str]]:
        assert repo_full_name == "octo-org/demo-app"
        assert branch == "main"
        files = [
            "package.json",
            "package-lock.json",
            "src/App.jsx",
            "vite.config.js",
            "Dockerfile",
            ".github/workflows/ci.yml",
        ]
        return {"files": files, "analysis_inputs": files}

    monkeypatch.setattr(repositories, "get_repository_analysis_inputs", _fake_get_repository_analysis_inputs)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/repositories/scan",
            headers=_auth_headers(),
            json={"repo_full_name": "octo-org/demo-app", "branch": "main"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["repo_full_name"] == "octo-org/demo-app"
    assert body["files"] == [
        "package.json",
        "package-lock.json",
        "src/App.jsx",
        "vite.config.js",
        "Dockerfile",
        ".github/workflows/ci.yml",
    ]
    assert body["stack"] == {
        "language": "javascript",
        "framework": "react",
        "package_manager": "npm",
        "has_docker": True,
        "has_existing_workflows": True,
        "recommended_workflow": "node-ci",
        "project_dir": ".",
        "detected_projects": [
            {"type": "docker", "path": ".", "framework": "docker", "package_manager": "unknown"},
            {"type": "node", "path": ".", "framework": "react", "package_manager": "npm"},
        ],
        "ci_warnings": [],
    }
    assert body["readiness"]["score"] >= 70
    assert body["readiness"]["grade"] in {"A", "B", "C"}
    assert body["readiness"]["recommended_next_actions"]


def test_scan_repository_returns_clear_github_error(monkeypatch):
    def _fake_get_repository_analysis_inputs(repo_full_name: str, branch: str | None = None) -> dict[str, list[str]]:
        raise GitHubToolError("Unable to read repository tree: repository or resource not found.")

    monkeypatch.setattr(repositories, "get_repository_analysis_inputs", _fake_get_repository_analysis_inputs)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/repositories/scan",
            headers=_auth_headers(),
            json={"repo_full_name": "octo-org/missing", "branch": "main"},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Unable to read repository tree: repository or resource not found."}


def test_scan_repository_reports_existing_workflow_compatibility_warnings(monkeypatch):
    def _fake_get_repository_analysis_inputs(repo_full_name: str, branch: str | None = None) -> dict[str, list[str]]:
        files = ["package.json", ".github/workflows/security.yml"]
        return {
            "files": files,
            "analysis_inputs": [
                *files,
                ".github/workflows/security.yml\n"
                "on: [pull_request]\n"
                "jobs:\n"
                "  dependency-review:\n"
                "    steps:\n"
                "      - uses: actions/dependency-review-action@v5\n",
            ],
        }

    monkeypatch.setattr(repositories, "get_repository_analysis_inputs", _fake_get_repository_analysis_inputs)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/repositories/scan",
            headers=_auth_headers(),
            json={"repo_full_name": "octo-org/demo-app"},
        )

    assert response.status_code == 200
    warnings = response.json()["stack"]["ci_warnings"]
    assert warnings
    assert warnings[0]["path"] == ".github/workflows/security.yml"
    assert "dependency-review-action" in warnings[0]["issue"]
    assert response.json()["readiness"]["score"] < 90
    assert response.json()["readiness"]["findings"]


@pytest.mark.asyncio
async def test_scan_repository_returns_clear_missing_token_error_and_audits(monkeypatch, db_session: AsyncSession):
    monkeypatch.setattr(github_tool.settings, "GITHUB_TOKEN", "")
    monkeypatch.setattr(github_tool, "_gh_client", None)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/repositories/scan",
            headers=_auth_headers(),
            json={"repo_full_name": "octo-org/demo-app", "branch": "main"},
        )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "GITHUB_TOKEN is not configured. Set it in backend/.env to enable GitHub integration."
    }

    result = await db_session.execute(
        select(Execution)
        .where(Execution.tool_name == "repository_analyzer", Execution.status == "failed")
        .order_by(Execution.started_at.desc())
    )
    execution = result.scalars().first()
    assert execution is not None
    assert execution.status == "failed"
    assert execution.requested_by == "repo-scan-test-user"
    assert "GITHUB_TOKEN is not configured" in (execution.details or "")


@pytest.mark.asyncio
async def test_installed_repositories_endpoint_lists_active_installations(db_session: AsyncSession):
    db_session.add(
        RepositoryInstallation(
            installation_id=88,
            repo_full_name="octo-org/demo-app",
            owner="octo-org",
            repo="demo-app",
            default_branch="main",
            status="active",
        )
    )
    await db_session.flush()

    with TestClient(app) as client:
        response = client.get("/api/v1/repositories/installed", headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["installation_id"] == 88
    assert body[0]["repo_full_name"] == "octo-org/demo-app"
    assert body[0]["status"] == "active"


@pytest.mark.asyncio
async def test_scan_repository_uses_installation_token_when_installed(monkeypatch, db_session: AsyncSession):
    db_session.add(
        RepositoryInstallation(
            installation_id=88,
            repo_full_name="octo-org/demo-app",
            owner="octo-org",
            repo="demo-app",
            default_branch="main",
            status="active",
        )
    )
    await db_session.flush()
    monkeypatch.setattr(repositories, "get_installation_access_token", lambda installation_id: "installation-token")
    monkeypatch.setattr(approvals, "get_installation_access_token", lambda installation_id: "installation-token")

    def _fake_get_repository_analysis_inputs(
        repo_full_name: str,
        branch: str | None = None,
        *,
        token: str | None = None,
    ) -> dict[str, list[str]]:
        assert token == "installation-token"
        files = ["package.json", "src/App.jsx"]
        return {"files": files, "analysis_inputs": files}

    monkeypatch.setattr(repositories, "get_repository_analysis_inputs", _fake_get_repository_analysis_inputs)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/repositories/scan",
            headers=_auth_headers(),
            json={"repo_full_name": "octo-org/demo-app"},
        )

    assert response.status_code == 200
    assert response.json()["stack"]["framework"] == "react"


def test_create_workflow_pr_requires_write_permission(monkeypatch):
    def _unexpected_create_workflow_pr(
        repo_full_name: str,
        *,
        overwrite_existing_workflow: bool = False,
    ) -> dict:
        raise AssertionError("create_workflow_pr should not be called")

    monkeypatch.setattr(github_tool, "create_workflow_pr", _unexpected_create_workflow_pr)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/repositories/create-workflow-pr",
            headers=_auth_headers("viewer"),
            json={"repo_full_name": "octo-org/demo-app"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_workflow_pr_returns_pr_details_and_audits(monkeypatch, db_session: AsyncSession):
    monkeypatch.setattr(repositories.settings, "ENABLE_HITL", False)

    def _fake_create_workflow_pr(
        repo_full_name: str,
        *,
        overwrite_existing_workflow: bool = False,
    ) -> dict:
        assert repo_full_name == "octo-org/demo-app"
        assert overwrite_existing_workflow is True
        return {
            "repo_full_name": "octo-org/demo-app",
            "detected_stack": {
                "language": "javascript",
                "framework": "react",
                "package_manager": "npm",
                "has_docker": False,
                "has_existing_workflows": False,
                "recommended_workflow": "node-ci",
                "project_dir": ".",
                "detected_projects": [],
                "ci_warnings": [],
            },
            "branch": "ai-cicd/setup-pipeline",
            "workflow_path": ".github/workflows/ai-generated-ci.yml",
            "pull_request_url": "https://github.com/octo-org/demo-app/pull/7",
            "pull_request": {"html_url": "https://github.com/octo-org/demo-app/pull/7"},
        }

    monkeypatch.setattr(github_tool, "create_workflow_pr", _fake_create_workflow_pr)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/repositories/create-workflow-pr",
            headers=_auth_headers("admin"),
            json={
                "repo_full_name": "octo-org/demo-app",
                "overwrite_existing_workflow": True,
            },
        )
        assert response.status_code == 200 and response.json()["approval_required"]
        approval_id = response.json()["approval_id"]
        decision = client.post(f"/api/v1/approvals/{approval_id}/decide",
                               headers=_auth_headers("admin"), json={"approved": True})
        assert decision.status_code == 200
        response = client.get("/api/v1/repositories/workflow-pr-status",
                              params={"repo_full_name": "octo-org/demo-app",
                                      "overwrite_existing_workflow": True},
                              headers=_auth_headers("admin"))

    assert response.status_code == 200
    assert response.json()["pull_request_url"] == "https://github.com/octo-org/demo-app/pull/7"
    assert response.json()["status"] == "completed"

    result = await db_session.execute(select(Execution).where(
        Execution.tool_name == "github_create_workflow_pr", Execution.source == "hitl",
    ))
    execution = result.scalar_one()
    assert execution.status == "completed"
    assert execution.requested_by == "repo-scan-test-user"
    assert "https://github.com/octo-org/demo-app/pull/7" in (execution.details or "")
    assert '"overwrite_existing_workflow": true' in (execution.tool_input or "")


@pytest.mark.asyncio
async def test_create_workflow_pr_creates_approval_when_hitl_enabled(monkeypatch, db_session: AsyncSession):
    monkeypatch.setattr(repositories.settings, "ENABLE_HITL", True)

    def _unexpected_create_workflow_pr(*args, **kwargs) -> dict:
        raise AssertionError("create_workflow_pr should wait for approval")

    monkeypatch.setattr(github_tool, "create_workflow_pr", _unexpected_create_workflow_pr)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/repositories/create-workflow-pr",
            headers=_auth_headers("admin"),
            json={
                "repo_full_name": "octo-org/demo-app",
                "overwrite_existing_workflow": True,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["repo_full_name"] == "octo-org/demo-app"
    assert body["status"] == "approval_required"
    assert body["approval_required"] is True
    assert body["approval_id"]

    approval_result = await db_session.execute(
        select(ApprovalRequest).where(ApprovalRequest.tool_name == "github_create_workflow_pr")
    )
    approval = approval_result.scalar_one()
    assert approval.status == "pending"
    assert approval.requested_by == "repo-scan-test-user"
    assert '"overwrite_existing_workflow": true' in (approval.tool_input or "")

    execution_result = await db_session.execute(
        select(Execution).where(Execution.tool_name == "github_create_workflow_pr")
    )
    execution = execution_result.scalar_one()
    assert execution.status == "pending"
    assert execution.approval_id == approval.id


@pytest.mark.asyncio
async def test_create_workflow_pr_uses_installation_token_when_installed(monkeypatch, db_session: AsyncSession):
    monkeypatch.setattr(repositories.settings, "ENABLE_HITL", False)

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
    await db_session.flush()
    monkeypatch.setattr(repositories, "get_installation_access_token", lambda installation_id: "installation-token")
    monkeypatch.setattr(approvals, "get_installation_access_token", lambda installation_id: "installation-token")

    def _fake_create_workflow_pr(
        repo_full_name: str,
        *,
        overwrite_existing_workflow: bool = False,
        token: str | None = None,
    ) -> dict:
        assert repo_full_name == "octo-org/demo-app"
        assert overwrite_existing_workflow is False
        assert token == "installation-token"
        return {
            "repo_full_name": "octo-org/demo-app",
            "detected_stack": {
                "language": "javascript",
                "framework": "react",
                "package_manager": "npm",
                "has_docker": False,
                "has_existing_workflows": False,
                "recommended_workflow": "node-ci",
            },
            "branch": "ai-cicd/setup-pipeline",
            "workflow_path": ".github/workflows/ai-generated-ci.yml",
            "pull_request_url": "https://github.com/octo-org/demo-app/pull/8",
        }

    monkeypatch.setattr(github_tool, "create_workflow_pr", _fake_create_workflow_pr)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/repositories/create-workflow-pr",
            headers=_auth_headers("admin"),
            json={"repo_full_name": "octo-org/demo-app"},
        )
        assert response.status_code == 200 and response.json()["approval_required"]
        approval_id = response.json()["approval_id"]
        decision = client.post(f"/api/v1/approvals/{approval_id}/decide",
                               headers=_auth_headers("admin"), json={"approved": True})
        assert decision.status_code == 200
        response = client.get("/api/v1/repositories/workflow-pr-status",
                              params={"repo_full_name": "octo-org/demo-app",
                                      "overwrite_existing_workflow": False},
                              headers=_auth_headers("admin"))

    assert response.status_code == 200
    assert response.json()["pull_request_url"] == "https://github.com/octo-org/demo-app/pull/8"


@pytest.mark.asyncio
async def test_create_workflow_pr_returns_clear_github_error_and_audits(monkeypatch, db_session: AsyncSession):
    monkeypatch.setattr(repositories.settings, "ENABLE_HITL", False)

    def _fake_create_workflow_pr(
        repo_full_name: str,
        *,
        overwrite_existing_workflow: bool = False,
    ) -> dict:
        raise GitHubToolError("Branch 'ai-cicd/setup-pipeline' already exists.")

    monkeypatch.setattr(github_tool, "create_workflow_pr", _fake_create_workflow_pr)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/repositories/create-workflow-pr",
            headers=_auth_headers("admin"),
            json={"repo_full_name": "octo-org/demo-app"},
        )
        assert response.status_code == 200 and response.json()["approval_required"]
        approval_id = response.json()["approval_id"]
        decision = client.post(f"/api/v1/approvals/{approval_id}/decide",
                               headers=_auth_headers("admin"), json={"approved": True})
        assert decision.status_code == 200
        response = client.get("/api/v1/repositories/workflow-pr-status",
                              params={"repo_full_name": "octo-org/demo-app",
                                      "overwrite_existing_workflow": False},
                              headers=_auth_headers("admin"))

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "already exists" in response.json()["message"]

    result = await db_session.execute(select(Execution).where(
        Execution.tool_name == "github_create_workflow_pr", Execution.source == "hitl",
    ))
    execution = result.scalar_one()
    assert execution.status == "failed"
    assert "already exists" in (execution.details or "")
