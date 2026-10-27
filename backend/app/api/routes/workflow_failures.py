"""Workflow failure diagnosis endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.core.security import require_permission
from app.schemas.schemas import (
    WorkflowFailureFixPRResponse, WorkflowFailureOut, WorkflowFailureImportRequest,
    WorkflowFailureSyncRequest, WorkflowFailureSyncResponse, WorkflowFailureIntegrationStatus,
)
from app.services.failure_prediction_service import FailurePredictionError, FailurePredictionUnavailable
from app.services.github_app_service import GitHubAppError
from app.services.workflow_failure_import_service import import_workflow_failure, sync_workflow_failures
from app.services.fix_pr_service import FixPRServiceError, create_fix_pr_for_failure
from app.services.workflow_failure_service import get_workflow_failure, list_workflow_failures
from app.tools.github_tool import GitHubToolError

router = APIRouter()


@router.get("", response_model=list[WorkflowFailureOut])
@router.get("/", response_model=list[WorkflowFailureOut], include_in_schema=False)
async def list_failures(
    limit: int = Query(default=50, ge=1, le=200),
    repo_full_name: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("workflow_failures:read")),
):
    """List recent GitHub Actions failure diagnoses."""
    return await list_workflow_failures(
        db,
        limit=limit,
        repo_full_name=repo_full_name,
        status=status,
        current_user=current_user,
    )


@router.get("/integration-status", response_model=WorkflowFailureIntegrationStatus)
async def integration_status(current_user: dict = Depends(require_permission("workflow_failures:read"))):
    """Expose configuration capabilities, never credential values."""
    return {
        "can_download_logs": bool(
            settings.GITHUB_TOKEN or (settings.GITHUB_APP_ID and settings.GITHUB_APP_PRIVATE_KEY)
        ),
        "webhook_configured": bool(settings.GITHUB_WEBHOOK_SECRET or settings.GITHUB_APP_WEBHOOK_SECRET),
        "default_repository": settings.GITHUB_REPO_FULL_NAME or None,
    }


@router.post("/sync", response_model=WorkflowFailureSyncResponse)
async def sync_failures(
    request: WorkflowFailureSyncRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("repositories:read")),
):
    """Import existing failed runs without waiting for a future webhook."""
    try:
        return await sync_workflow_failures(db, request, current_user)
    except (GitHubToolError, GitHubAppError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import", response_model=WorkflowFailureOut)
async def import_failure(
    request: WorkflowFailureImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("failures:predict")),
):
    """Diagnose pasted logs for a particular run and save them to this workspace."""
    try:
        return await import_workflow_failure(db, request, current_user)
    except FailurePredictionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (GitHubToolError, FailurePredictionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{failure_id}/create-fix-pr", response_model=WorkflowFailureFixPRResponse)
async def create_failure_fix_pr(
    failure_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("repositories:write")),
):
    """Request human approval for a GitHub workflow fix pull request."""
    record = await get_workflow_failure(db, str(failure_id), current_user=current_user)
    if not record:
        raise HTTPException(status_code=404, detail="Workflow failure diagnosis not found.")
    try:
        return await create_fix_pr_for_failure(db, str(failure_id), current_user)
    except FixPRServiceError as exc:
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{failure_id}", response_model=WorkflowFailureOut)
async def get_failure(
    failure_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("workflow_failures:read")),
):
    """Fetch one GitHub Actions failure diagnosis by id."""
    record = await get_workflow_failure(db, str(failure_id), current_user=current_user)
    if not record:
        raise HTTPException(status_code=404, detail="Workflow failure diagnosis not found.")
    return record
