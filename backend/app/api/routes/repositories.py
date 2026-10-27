"""Repository inspection endpoints."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_permission
from app.schemas.schemas import (
    RepositoryInstallationOut,
    RepositoryScanRequest,
    RepositoryScanResponse,
    RepositoryWorkflowPRRequest,
    RepositoryWorkflowPRResponse,
)
from app.services import audit_service
from app.services.github_app_service import (
    GitHubAppError,
    get_installation_access_token,
    get_installation_for_repo,
    list_installed_repositories,
)
from app.services.cicd_readiness_service import assess_cicd_readiness
from app.services.repo_analyzer import detect_stack
from app.tools.github_tool import GitHubToolError, get_repository_analysis_inputs

from app.services.workflow_pr_request_service import latest_workflow_pr, request_workflow_pr

router = APIRouter()


async def _installation_token_for_repo(db: AsyncSession, repo_full_name: str) -> str | None:
    """Return a GitHub App installation token for installed repos, or None for PAT fallback."""
    installation = await get_installation_for_repo(db, repo_full_name)
    if not installation:
        return None
    return get_installation_access_token(installation.installation_id)


@router.get("/installed", response_model=list[RepositoryInstallationOut])
async def installed_repositories(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("repositories:read")),
):
    """List repositories installed through the GitHub App."""
    return await list_installed_repositories(db)


@router.post("/scan", response_model=RepositoryScanResponse)
async def scan_repository(
    request: RepositoryScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("repositories:read")),
):
    """Fetch a GitHub repository tree and analyze its CI/CD stack."""
    try:
        token = await _installation_token_for_repo(db, request.repo_full_name)
        analysis = (
            get_repository_analysis_inputs(request.repo_full_name, request.branch, token=token)
            if token
            else get_repository_analysis_inputs(request.repo_full_name, request.branch)
        )
        files = analysis["files"]
        stack = detect_stack(analysis["analysis_inputs"])
        readiness = assess_cicd_readiness(files, stack)
        await audit_service.log_repo_analysis(
            db,
            repo_full_name=request.repo_full_name,
            files_analyzed=len(files),
            detected_stack=stack,
            actor=current_user.get("username") or current_user.get("sub") or "unknown",
            source="api",
        )
    except (GitHubToolError, GitHubAppError) as exc:
        await audit_service.log_execution(
            db,
            tool_name="repository_analyzer",
            action_summary=f"Failed to analyze repository {request.repo_full_name}",
            status="failed",
            actor=current_user.get("username") or current_user.get("sub") or "unknown",
            tool_input={"repo": request.repo_full_name, "branch": request.branch},
            tool_output={},
            error=str(exc),
            source="api",
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {
        "repo_full_name": request.repo_full_name,
        "files": files,
        "stack": stack,
        "readiness": readiness,
    }


@router.get("/integration-status")
async def repository_integration_status(current_user: dict = Depends(require_permission("repositories:read"))):
    return {"credentials_configured": bool(settings.GITHUB_TOKEN or (
        settings.GITHUB_APP_ID and settings.GITHUB_APP_PRIVATE_KEY
    ))}


@router.get("/workflow-pr-status", response_model=RepositoryWorkflowPRResponse | None)
async def workflow_pr_status(
    repo_full_name: str = Query(min_length=3, max_length=255),
    overwrite_existing_workflow: bool = False,
    approval_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("repositories:write")),
):
    """Return own latest review, or a specific review visible to this member."""
    try:
        result = await latest_workflow_pr(
            db, repo_full_name, overwrite_existing_workflow, current_user,
            str(approval_id) if approval_id else None,
        )
        if approval_id and result is None:
            raise HTTPException(status_code=404, detail="Workflow PR review not found.")
        return result
    except GitHubToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/create-workflow-pr", response_model=RepositoryWorkflowPRResponse, response_model_exclude_none=True)
async def create_repository_workflow_pr(
    request: RepositoryWorkflowPRRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("repositories:write")),
):
    """Save or reuse human approval for a workflow PR. All writes wait for review."""
    try:
        return await request_workflow_pr(db, request.repo_full_name, request.overwrite_existing_workflow, current_user)
    except GitHubToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
