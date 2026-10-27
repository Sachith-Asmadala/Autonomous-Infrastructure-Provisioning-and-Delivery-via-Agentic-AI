"""Persistence helpers for GitHub Actions workflow failure diagnoses."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import ApprovalRequest, WorkflowFailure
from app.services.activity_visibility_service import activity_actor, can_view_all_activity


async def create_workflow_failure(
    db: AsyncSession,
    *,
    repo_full_name: str,
    workflow_run_id: int,
    workflow_name: str | None = None,
    branch: str | None = None,
    conclusion: str = "failure",
    workflow_url: str | None = None,
    log_excerpt: str | None = None,
    predicted_label: str | None = None,
    confidence: float | None = None,
    suggested_fix: str | None = None,
    recommendation: dict[str, Any] | None = None,
    fix_pr_url: str | None = None,
    status: str = "diagnosed",
    requested_by: str | None = None,
    diagnosis_error: str | None = None,
) -> WorkflowFailure:
    """Create and flush a workflow failure diagnosis record."""
    record = WorkflowFailure(
        repo_full_name=repo_full_name,
        workflow_run_id=workflow_run_id,
        workflow_name=workflow_name,
        branch=branch,
        conclusion=conclusion,
        workflow_url=workflow_url,
        log_excerpt=log_excerpt,
        predicted_label=predicted_label,
        confidence=confidence,
        suggested_fix=suggested_fix,
        recommendation_json=json.dumps(recommendation, ensure_ascii=False) if recommendation else None,
        fix_pr_url=fix_pr_url,
        status=status,
        requested_by=requested_by,
        diagnosis_error=diagnosis_error,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return record


async def list_workflow_failures(
    db: AsyncSession,
    *,
    limit: int = 50,
    repo_full_name: str | None = None,
    status: str | None = None,
    current_user: dict | None = None,
) -> list[WorkflowFailure]:
    """List recent workflow failure diagnoses."""
    stmt = select(WorkflowFailure).order_by(WorkflowFailure.created_at.desc()).limit(min(max(limit, 1), 200))
    if current_user is not None and not can_view_all_activity(current_user):
        stmt = stmt.where(WorkflowFailure.requested_by == activity_actor(current_user))
    if repo_full_name:
        stmt = stmt.where(WorkflowFailure.repo_full_name == repo_full_name)
    if status:
        stmt = stmt.where(WorkflowFailure.status == status)
    result = await db.execute(stmt)
    records = list(result.scalars().all())
    await _attach_pending_approvals(db, records)
    return records


async def get_workflow_failure(
    db: AsyncSession, failure_id: str, *, current_user: dict | None = None,
) -> WorkflowFailure | None:
    """Fetch a workflow failure diagnosis by id."""
    record = await db.get(WorkflowFailure, failure_id)
    if record and current_user is not None and not can_view_all_activity(current_user):
        if record.requested_by != activity_actor(current_user):
            return None
    if record:
        await _attach_pending_approvals(db, [record])
    return record


async def _attach_pending_approvals(db: AsyncSession, records: list[WorkflowFailure]) -> None:
    """Derive current approval availability without changing saved failure status."""
    waiting = {record.id: record for record in records if record.status == "approval_pending"}
    for record in records:
        setattr(record, "has_pending_approval", False)
    if not waiting:
        return
    approvals = (await db.execute(select(ApprovalRequest.tool_input).where(
        ApprovalRequest.tool_name == "github_create_fix_pr",
        ApprovalRequest.status == "pending",
        or_(ApprovalRequest.expires_at.is_(None), ApprovalRequest.expires_at > datetime.now(timezone.utc)),
    ))).scalars().all()
    for tool_input in approvals:
        try:
            failure_id = json.loads(tool_input or "{}").get("workflow_failure_id")
        except (ValueError, AttributeError):
            continue
        if isinstance(failure_id, str) and failure_id in waiting:
            setattr(waiting[failure_id], "has_pending_approval", True)


def workflow_failure_values(
    *,
    repo_full_name: str | None,
    workflow_run_id: Any,
    workflow_name: str | None,
    branch: str | None,
    conclusion: str | None,
    workflow_url: str | None,
    log_excerpt: str | None,
    prediction: dict[str, Any] | None,
    error: str | None,
) -> dict[str, Any]:
    """Build normalized values for storing a webhook diagnosis."""
    prediction = prediction or {}
    return {
        "repo_full_name": repo_full_name or "unknown",
        "workflow_run_id": int(workflow_run_id or 0),
        "workflow_name": workflow_name,
        "branch": branch,
        "conclusion": conclusion or "failure",
        "workflow_url": workflow_url,
        "log_excerpt": log_excerpt,
        "predicted_label": prediction.get("label"),
        "confidence": prediction.get("confidence"),
        "suggested_fix": prediction.get("suggested_fix"),
        "recommendation": prediction.get("recommendation"),
        "fix_pr_url": None,
        "status": "diagnosis_failed" if error else "diagnosed",
        "requested_by": "github_webhook",
        "diagnosis_error": error,
    }
