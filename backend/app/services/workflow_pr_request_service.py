"""Persist workflow PR reviews and expose the real execution outcome."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import ApprovalRequest, Execution, User
from app.services import audit_service
from app.services.activity_visibility_service import activity_actor, can_view_all_activity
from app.tools.github_tool import clean_workflow_log, _validate_repo_full_name


def _input(record: ApprovalRequest) -> dict:
    try:
        value = json.loads(record.tool_input or "{}")
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def _expired(record: ApprovalRequest) -> bool:
    return bool(record.expires_at and record.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc))


async def _requests(db: AsyncSession, repo: str, actor: str, overwrite: bool) -> list[ApprovalRequest]:
    records = (await db.execute(select(ApprovalRequest).where(
        ApprovalRequest.requested_by == actor, ApprovalRequest.tool_name == "github_create_workflow_pr",
    ).order_by(ApprovalRequest.created_at.desc()))).scalars().all()
    return [r for r in records if str(_input(r).get("repo_full_name", "")).lower() == repo.lower()
            and bool(_input(r).get("overwrite_existing_workflow")) == overwrite]


async def request_workflow_pr(db: AsyncSession, repo: str, overwrite: bool, current_user: dict) -> dict:
    """Repeated submissions reuse the actor's unexpired review; never execute here."""
    repo = _validate_repo_full_name(repo)
    actor = activity_actor(current_user)
    if db.get_bind().dialect.name == "sqlite":
        await db.execute(update(ApprovalRequest).where(ApprovalRequest.requested_by == actor)
                         .values(status=ApprovalRequest.status))
    else:
        await db.execute(select(User.id).where(User.username == actor).with_for_update())
    for existing in await _requests(db, repo, actor, overwrite):
        if existing.status != "pending":
            continue
        if not _expired(existing):
            return await workflow_pr_response(db, existing)
        existing.status = "timed_out"
        await db.execute(update(Execution).where(
            Execution.approval_id == existing.id, Execution.status == "pending",
        ).values(status="cancelled", completed_at=datetime.now(timezone.utc),
                 details=json.dumps({"error": "Approval request expired before execution."})))
        await audit_service.log_approval_decision(
            db, approval_id=existing.id, decision="timed_out",
            tool_name=existing.tool_name or "github_create_workflow_pr",
            actor=actor, session_id=existing.session_id, reason="Expired workflow PR review replaced by a new request.",
        )
    now = datetime.now(timezone.utc)
    tool_input = json.dumps({"repo_full_name": repo, "overwrite_existing_workflow": overwrite})
    approval = ApprovalRequest(
        requested_by=actor, tool_name="github_create_workflow_pr", tool_input=tool_input,
        action="Create GitHub Actions workflow pull request", risk_level="medium",
        summary=f"Approve workflow PR creation for {repo}.", status="pending",
        expires_at=now + timedelta(seconds=settings.HITL_APPROVAL_TIMEOUT_SECONDS),
    )
    db.add(approval)
    await db.flush()
    db.add(Execution(
        requested_by=actor, approval_id=approval.id, tool_name=approval.tool_name, tool_input=tool_input,
        status="pending", summary=f"Approval required before creating workflow PR for {repo}",
        details=json.dumps({"approval_required": True, "approval_id": approval.id}),
        source="api", started_at=now,
    ))
    await audit_service.log_execution(
        db, tool_name="github_workflow_pr", action_summary=f"Approval required before creating workflow PR for {repo}",
        status="pending", actor=actor, tool_input={"repo": repo, "overwrite_existing_workflow": overwrite},
        tool_output={"approval_id": approval.id}, source="api",
    )
    await db.flush()
    return await workflow_pr_response(db, approval)


async def latest_workflow_pr(
    db: AsyncSession, repo: str, overwrite: bool, current_user: dict, approval_id: str | None = None,
) -> dict | None:
    repo = _validate_repo_full_name(repo)
    if approval_id:
        record = await db.get(ApprovalRequest, approval_id)
        if not record or record.tool_name != "github_create_workflow_pr":
            return None
        if record.requested_by != activity_actor(current_user) and not can_view_all_activity(current_user):
            return None
        if str(_input(record).get("repo_full_name", "")).lower() != repo.lower():
            return None
        return await workflow_pr_response(db, record)
    records = await _requests(db, repo, activity_actor(current_user), overwrite)
    return await workflow_pr_response(db, records[0]) if records else None


async def workflow_pr_response(db: AsyncSession, approval: ApprovalRequest) -> dict:
    response = {"repo_full_name": str(_input(approval).get("repo_full_name", "")), "approval_id": approval.id,
                "approval_status": approval.status, "expires_at": approval.expires_at,
                "approval_required": False}
    if approval.status == "pending":
        response.update(status="timed_out" if _expired(approval) else "approval_required",
                        approval_required=not _expired(approval),
                        message="This review expired. Request a new approval." if _expired(approval)
                        else "Human approval is required before sending this pull request.")
    elif approval.status == "approved":
        execution = await db.scalar(select(Execution).where(
            Execution.approval_id == approval.id, Execution.source == "hitl",
        ).order_by(Execution.completed_at.desc(), Execution.started_at.desc()).limit(1))
        try:
            details = json.loads(execution.details or "{}") if execution else {}
        except ValueError:
            details = {}
        if not isinstance(details, dict):
            details = {}
        if execution and execution.status == "completed" and details.get("pull_request_url"):
            response.update({key: details[key] for key in (
                "detected_stack", "branch", "workflow_path", "pull_request_url",
            ) if key in details})
            response.update(status="completed", message="Workflow pull request is ready for review.")
        else:
            error = details.get("error") or (
                "The approved action did not produce a pull request. Check the audit log and retry."
            )
            response.update(status="failed", message=clean_workflow_log(str(error)))
        if execution:
            response.update(execution_id=execution.id, execution_status=execution.status)
    else:
        response.update(
            status=approval.status, message=f"The review was {approval.status}. You can request a new review.",
        )
    return response
