"""
HITL Approval endpoints.

Flow
----
1. Agent detects HIGH/CRITICAL risk → calls `create_approval_request()` helper.
2. Record lands in `approval_requests` table with status="pending".
3. A reviewer polls GET /api/v1/approvals/ to see permitted pending items.
4. A reviewer calls POST /api/v1/approvals/{id}/decide with approved=true|false.
   Developers review their own authorized work; admins review shared work.
5. If approved, we execute the tool and log an Execution record.
   If rejected, we mark the request "rejected" and log a cancelled Execution.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.logging import logger
from app.core.security import has_permission, require_permission
from app.models.models import ApprovalRequest, Execution
from app.schemas.schemas import ApprovalDecision, ApprovalRequestOut
from app.services import audit_service
from app.services.activity_visibility_service import activity_actor, can_view_all_activity
from app.services.approval_policy_service import (
    approval_response, can_decide_approval, can_review_shared_approvals, require_approval_reviewer,
)
from app.services.user_management_service import apply_status_change
from app.services.fix_pr_service import FixPRServiceError, create_fix_pr_for_failure, mark_fix_pr_rejected
from app.tools.github_tool import clean_workflow_log
from app.services.github_app_service import GitHubAppError, get_installation_access_token, get_installation_for_repo

router = APIRouter()

_SENSITIVE_TEXT_PATTERNS = [
    re.compile(r"(gh[pousr]_|github_pat_)[A-Za-z0-9_]+", re.IGNORECASE),
    re.compile(r"(Bearer\s+)[^\s\"']+", re.IGNORECASE),
    re.compile(
        r"(?i)((token|secret|api[_-]?key|private[_-]?key|password|credential|access[_-]?key)"
        r"\s*[:=]\s*)[^\s\"']+"
    ),
]


def redact_tool_input(value):
    """Return approval tool input safe enough for persistence and audit display."""
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            key_text = str(key)
            if any(part in key_text.lower() for part in ("token", "secret", "key", "password", "credential")):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_tool_input(item)
        return redacted
    if isinstance(value, list):
        return [redact_tool_input(item) for item in value]
    if isinstance(value, str):
        redacted = value
        for pattern in _SENSITIVE_TEXT_PATTERNS:
            redacted = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", redacted)
        return redacted
    return value


# Helper used by the agent

async def create_approval_request(
    *,
    db: AsyncSession,
    session_id: str,
    requested_by: str,
    tool_name: str,
    tool_input: dict,
    action: str,
    risk_level: str,
    summary: str,
    timeout_seconds: int = 300,
) -> ApprovalRequest:
    """
    Persist a pending approval and return the record.

    Called by the agent when it classifies an action as HIGH or CRITICAL risk.
    """
    from datetime import timedelta
    expires = datetime.now(tz=timezone.utc) + timedelta(seconds=timeout_seconds)
    safe_tool_input = redact_tool_input(tool_input)
    record = ApprovalRequest(
        id=str(uuid.uuid4()),
        session_id=session_id,
        requested_by=requested_by,
        tool_name=tool_name,
        tool_input=json.dumps(safe_tool_input),
        action=action,
        risk_level=risk_level,
        summary=summary,
        status="pending",
        expires_at=expires,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    logger.info(
        "hitl.approval.created",
        approval_id=record.id,
        tool=tool_name,
        risk=risk_level,
        user=requested_by,
    )
    return record


async def _github_auth_for_repo(db: AsyncSession, repo_full_name: str) -> tuple[str | None, str, int | None]:
    """Return a token override plus safe auth-mode metadata for a repository."""
    installation = await get_installation_for_repo(db, repo_full_name)
    if not installation:
        return None, "pat_fallback", None
    return (
        get_installation_access_token(installation.installation_id),
        "github_app_installation",
        int(installation.installation_id),
    )


# Routes

@router.get("", response_model=list[ApprovalRequestOut])
@router.get("/", response_model=list[ApprovalRequestOut], include_in_schema=False)
async def list_pending_approvals(
    status_filter: Optional[str] = "pending",
    scope: Literal["all", "mine"] = "all",
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("approvals:read")),
):
    """List approval requests (default: pending only)."""
    stmt = select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc())
    # Admins still need the shared queue to perform authorized reviews.
    # Personal dashboards request "mine"; members without shared review permission
    # can only read their own requests even if they explicitly request "all".
    if scope == "mine" or not can_review_shared_approvals(current_user):
        stmt = stmt.where(ApprovalRequest.requested_by == activity_actor(current_user))
    if status_filter:
        stmt = stmt.where(ApprovalRequest.status == status_filter)
    result = await db.execute(stmt)
    return [approval_response(record, current_user) for record in result.scalars().all()]


@router.get("/{approval_id}", response_model=ApprovalRequestOut)
async def get_approval(
    approval_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("approvals:read")),
):
    """Fetch a single approval request by ID."""
    stmt = select(ApprovalRequest).where(ApprovalRequest.id == str(approval_id))
    if not can_view_all_activity(current_user) and not can_review_shared_approvals(current_user):
        stmt = stmt.where(ApprovalRequest.requested_by == activity_actor(current_user))
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Approval request not found.")

    if record.tool_name == "admin_set_user_active" and not has_permission(current_user.get("role"), "users:manage"):
        raise HTTPException(status_code=403, detail="Only an administrator can decide account status changes.")
    return approval_response(record, current_user)


@router.post("/{approval_id}/decide", status_code=200)
async def decide_approval(
    approval_id: UUID,
    decision: ApprovalDecision,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_approval_reviewer),
):
    """
    Approve or reject a pending HITL approval request.
    Admins review shared work; developers decide only their own work
    and can approve only tools authorized for their role.

    On approval  → the tool is executed immediately and an Execution record is created.
    On rejection → the request is marked rejected and a cancelled Execution is logged.
    """
    query = select(ApprovalRequest).where(ApprovalRequest.id == str(approval_id))
    if not can_review_shared_approvals(current_user):
        query = query.where(ApprovalRequest.requested_by == activity_actor(current_user))
    record: Optional[ApprovalRequest] = (await db.execute(query)).scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Approval request not found.")

    if record.tool_name == "admin_set_user_active" and not has_permission(current_user.get("role"), "users:manage"):
        raise HTTPException(status_code=403, detail="Only an administrator can decide account status changes.")

    if not can_decide_approval(current_user, record, approved=decision.approved):
        raise HTTPException(status_code=403, detail="This action requires review by an administrator.")

    # Serialize decisions before checking status, including simultaneous
    # reviews by the developer and an admin. SQLite has no row locks;
    # a no-op write acquires its transaction lock.
    if db.get_bind().dialect.name == "sqlite":
        await db.execute(
            update(ApprovalRequest).where(ApprovalRequest.id == str(approval_id))
            .values(status=ApprovalRequest.status)
        )
    record = (await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == str(approval_id))
        .with_for_update().execution_options(populate_existing=True)
    )).scalar_one()

    if record.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Approval request is already '{record.status}' — cannot decide again.",
        )

    decider = current_user.get("username", "unknown")

    # Check expiry
    if record.expires_at:
        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
    else:
        expires_at = None

    if expires_at and datetime.now(tz=timezone.utc) > expires_at:
        record.status = "timed_out"
        await db.execute(update(Execution).where(
            Execution.approval_id == record.id, Execution.status == "pending",
        ).values(status="cancelled", completed_at=datetime.now(timezone.utc),
                 details=json.dumps({"error": "Approval request expired before execution."})))
        await audit_service.log_approval_decision(
            db,
            approval_id=record.id,
            decision="timed_out",
            tool_name=record.tool_name or "",
            actor=decider,
            session_id=record.session_id,
            reason="Approval request expired before decision.",
        )
        await db.flush()
        await db.commit()
        raise HTTPException(status_code=410, detail="Approval request has expired.")

    now = datetime.now(tz=timezone.utc)

    if decision.approved:
        # Execute the tool
        tool_input = json.loads(record.tool_input or "{}")
        if record.tool_name == "admin_set_user_active":
            result = await apply_status_change(db, tool_input, current_user)
            exec_details = json.dumps(result)
            exec_status = "completed"
        elif record.tool_name == "github_create_fix_pr":
            try:
                result = await create_fix_pr_for_failure(
                    db,
                    tool_input.get("workflow_failure_id", ""),
                    {"username": decider, "role": current_user.get("role")},
                    bypass_approval=True,
                    audit=False,
                )
                exec_details = json.dumps(result, ensure_ascii=False)
                exec_status = "completed" if result.get("status") in {"fix_pr_created", "already_created"} else "failed"
            except FixPRServiceError as exc:
                exec_details = json.dumps({"error": str(exc)}, ensure_ascii=False)
                exec_status = "failed"
        elif record.tool_name == "github_create_workflow_pr":
            exec_details, exec_status = await _create_workflow_pr_from_approval(
                db=db,
                tool_input=tool_input,
                actor=decider,
                session_id=record.session_id,
            )
        elif record.tool_name == "github_trigger_workflow":
            exec_details, exec_status = await _trigger_workflow_from_approval(
                db=db,
                tool_input=tool_input,
            )
        else:
            exec_details, exec_status = _dispatch_tool(record.tool_name or "", tool_input)

        record.status = "approved"
        record.decided_by = decider
        record.decision_note = decision.note
        record.decided_at = now

        execution = Execution(
            id=str(uuid.uuid4()),
            approval_id=record.id,
            session_id=record.session_id,
            requested_by=record.requested_by,
            tool_name=record.tool_name,
            tool_input=record.tool_input,
            status=exec_status,
            summary=f"Approved by {decider}. {record.summary}",
            details=exec_details,
            source="hitl",
            started_at=now,
            completed_at=datetime.now(tz=timezone.utc),
        )
        db.add(execution)
        await db.execute(update(Execution).where(
            Execution.approval_id == record.id, Execution.status == "pending",
        ).values(status=exec_status, details=exec_details, completed_at=datetime.now(timezone.utc)))
        await audit_service.log_approval_decision(
            db,
            approval_id=record.id,
            decision="approved",
            tool_name=record.tool_name or "",
            actor=decider,
            session_id=record.session_id,
            reason=decision.note,
        )
        await db.flush()

        logger.info(
            "hitl.approval.approved",
            approval_id=str(approval_id),
            tool=record.tool_name,
            decided_by=decider,
            exec_status=exec_status,
        )
        return {
            "approval_id": str(approval_id),
            "status": "approved",
            "note": decision.note,
            "decided_by": decider,
            "execution_id": execution.id,
            "execution_status": exec_status,
            "execution_details": exec_details,
        }
    else:
        # Reject / cancel
        tool_input = json.loads(record.tool_input or "{}")
        if record.tool_name == "github_create_fix_pr" and tool_input.get("workflow_failure_id"):
            await mark_fix_pr_rejected(
                db,
                tool_input["workflow_failure_id"],
                decided_by=decider,
                note=decision.note,
            )

        record.status = "rejected"
        record.decided_by = decider
        record.decision_note = decision.note
        record.decided_at = now

        execution = Execution(
            id=str(uuid.uuid4()),
            approval_id=record.id,
            session_id=record.session_id,
            requested_by=record.requested_by,
            tool_name=record.tool_name,
            tool_input=record.tool_input,
            status="cancelled",
            summary=f"Rejected by {decider}. {record.summary}",
            details=f"Rejection note: {decision.note or '(none)'}",
            source="hitl",
            started_at=now,
            completed_at=now,
        )
        db.add(execution)
        await audit_service.log_approval_decision(
            db,
            approval_id=record.id,
            decision="rejected",
            tool_name=record.tool_name or "",
            actor=decider,
            session_id=record.session_id,
            reason=decision.note,
        )
        await db.execute(update(Execution).where(
            Execution.approval_id == record.id, Execution.status == "pending",
        ).values(status="cancelled", completed_at=now, details="Rejected before execution."))
        await db.flush()

        logger.info(
            "hitl.approval.rejected",
            approval_id=str(approval_id),
            tool=record.tool_name,
            decided_by=decider,
        )
        return {
            "approval_id": str(approval_id),
            "status": "rejected",
            "note": decision.note,
            "decided_by": decider,
        }


async def _create_workflow_pr_from_approval(
    *,
    db: AsyncSession,
    tool_input: dict,
    actor: str,
    session_id: str | None,
) -> tuple[str, str]:
    """Create an approved workflow PR using a GitHub App token when installed."""
    repo_full_name = str(tool_input.get("repo_full_name") or "").strip()
    if not repo_full_name:
        return json.dumps({"error": "repo_full_name is required."}, ensure_ascii=False), "failed"

    try:
        from app.tools.github_tool import create_workflow_pr

        token, auth_mode, installation_id = await _github_auth_for_repo(db, repo_full_name)
        token_kwargs: dict = {"token": token} if token else {}
        result = await run_in_threadpool(
            create_workflow_pr, repo_full_name,
            overwrite_existing_workflow=bool(tool_input.get("overwrite_existing_workflow")),
            **token_kwargs,
        )
        result["auth_mode"] = auth_mode
        if installation_id is not None:
            result["installation_id"] = installation_id
        await audit_service.log_workflow_pr_creation(
            db,
            repo_full_name=result.get("repo_full_name") or repo_full_name,
            branch=result.get("branch") or "",
            pull_request_url=result.get("pull_request_url"),
            actor=actor,
            session_id=session_id,
            source="hitl",
        )
        return json.dumps(result, ensure_ascii=False, default=str), "completed"
    except Exception as exc:
        error = clean_workflow_log(str(exc))
        await audit_service.log_workflow_pr_creation(
            db,
            repo_full_name=repo_full_name,
            branch="",
            pull_request_url=None,
            status="failed",
            error=error,
            actor=actor,
            session_id=session_id,
            source="hitl",
        )
        return json.dumps({"error": error}, ensure_ascii=False), "failed"


async def _trigger_workflow_from_approval(
    *,
    db: AsyncSession,
    tool_input: dict,
) -> tuple[str, str]:
    """Trigger an approved workflow using GitHub App auth when installed."""
    repo_full_name = str(tool_input.get("repo_full_name") or "").strip()
    workflow_id = str(tool_input.get("workflow_id") or "").strip()
    ref = str(tool_input.get("ref") or "main").strip() or "main"
    inputs = tool_input.get("inputs") if isinstance(tool_input.get("inputs"), dict) else None
    if not repo_full_name or not workflow_id:
        return json.dumps({"error": "repo_full_name and workflow_id are required."}), "failed"

    try:
        from app.tools.github_tool import trigger_workflow

        token, auth_mode, installation_id = await _github_auth_for_repo(db, repo_full_name)
        output = trigger_workflow(
            repo_full_name=repo_full_name,
            workflow_id=workflow_id,
            ref=ref,
            inputs=inputs,
            token=token,
        )
        details = {
            "repo_full_name": repo_full_name,
            "workflow_id": workflow_id,
            "ref": ref,
            "inputs": inputs or {},
            "result": output,
            "auth_mode": auth_mode,
        }
        if installation_id is not None:
            details["installation_id"] = installation_id
        status = "failed" if output.lower().startswith(("github api error", "failed")) else "completed"
        return json.dumps(details, ensure_ascii=False), status
    except (GitHubAppError, Exception) as exc:
        return json.dumps({"error": str(exc), "repo_full_name": repo_full_name}, ensure_ascii=False), "failed"


def _dispatch_tool(tool_name: str, tool_input: dict) -> tuple[str, str]:
    """
    Execute the approved tool and return (details_string, status_string).

    Extend this dispatcher as new tools are added to tools_registry.
    """
    try:
        if tool_name == "docker_restart_container":
            from app.tools.docker_tool import restart_container
            details = restart_container(tool_input.get("container_name", ""))
        elif tool_name == "docker_stop_container":
            from app.tools.docker_tool import stop_container
            details = stop_container(tool_input.get("container_name", ""))
        elif tool_name == "docker_start_container":
            from app.tools.docker_tool import start_container
            details = start_container(tool_input.get("container_name", ""))
        elif tool_name == "docker_run_container":
            from app.tools.docker_tool import run_container
            details = run_container(**tool_input)
        elif tool_name in {"github_trigger_workflow", "github_create_workflow_pr", "github_create_fix_pr"}:
            details = f"GitHub tool '{tool_name}' requires the async approval dispatcher for auth resolution."
            return details, "failed"
        elif tool_name == "execute_shell_command":
            from app.tools.shell_tool import execute_safe_shell_command
            details = execute_safe_shell_command(tool_input.get("command", ""))
        else:
            details = f"Unknown tool '{tool_name}' — no dispatcher registered."
            return details, "failed"
        return details, "completed"
    except Exception as exc:
        logger.error("hitl.dispatch_tool.error", tool=tool_name, error=str(exc))
        return f"Tool execution error: {exc}", "failed"
