"""Comprehensive audit logging service for all CI/CD operations."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.models import Execution


class AuditError(RuntimeError):
    """Raised when audit record creation fails."""


MAX_AUDIT_TEXT_LENGTH = 1000
MAX_AUDIT_LOG_PREVIEW_LENGTH = 500


def _truncate_text(value: str, limit: int = MAX_AUDIT_TEXT_LENGTH) -> str:
    """Return a compact string safe for audit records."""
    if len(value) <= limit:
        return value
    return f"{value[:limit]}... [truncated {len(value) - limit} chars]"


def _summarize_context(context: Mapping[str, Any] | None) -> dict[str, Any]:
    """Summarize user-provided agent context without storing large logs or secrets."""
    summary: dict[str, Any] = {}
    for key, value in (context or {}).items():
        key_lower = str(key).lower()
        if any(pattern in key_lower for pattern in ["token", "secret", "key", "password", "credential", "api_key"]):
            summary[str(key)] = "[REDACTED]"
        elif key_lower in {"log_text", "logs", "raw_log"}:
            text = str(value or "")
            summary[str(key)] = {
                "length": len(text),
                "preview": _truncate_text(text, MAX_AUDIT_LOG_PREVIEW_LENGTH),
            }
        elif isinstance(value, list):
            summary[str(key)] = {
                "count": len(value),
                "preview": [_truncate_text(str(item), 200) for item in value[:10]],
            }
        elif isinstance(value, dict):
            summary[str(key)] = {
                nested_key: "[REDACTED]" if any(
                    pattern in str(nested_key).lower()
                    for pattern in ["token", "secret", "key", "password", "credential", "api_key"]
                ) else _truncate_text(str(nested_value), 200)
                for nested_key, nested_value in list(value.items())[:20]
            }
        else:
            summary[str(key)] = _truncate_text(str(value), 300)
    return summary


def _summarize_agent_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep important agent metadata while avoiding oversized generated content."""
    safe: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        key_lower = str(key).lower()
        if any(pattern in key_lower for pattern in ["token", "secret", "key", "password", "credential", "api_key"]):
            safe[str(key)] = "[REDACTED]"
        elif key_lower in {"workflow_yaml", "log_text", "logs", "raw_log"}:
            text = str(value or "")
            safe[str(key)] = {"length": len(text), "preview": _truncate_text(text, 500)}
        elif key_lower == "files" and isinstance(value, list):
            safe[str(key)] = {"count": len(value), "preview": value[:20]}
        elif isinstance(value, dict):
            safe[str(key)] = _redact_sensitive_values(value)
        elif isinstance(value, list):
            safe[str(key)] = [_truncate_text(str(item), 200) for item in value[:20]]
        else:
            safe[str(key)] = _truncate_text(str(value), 500)
    return safe


def _redact_sensitive_values(data: Any, depth: int = 0) -> Any:
    """Recursively redact tokens, keys, and secrets from audit data."""
    if depth > 10:  # Prevent runaway recursion
        return data

    if isinstance(data, dict):
        redacted = {}
        for key, value in data.items():
            key_lower = key.lower()
            # Redact sensitive keys
            if any(
                pattern in key_lower
                for pattern in ["token", "secret", "key", "password", "credential", "api_key"]
            ):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_sensitive_values(value, depth + 1)
        return redacted
    elif isinstance(data, (list, tuple)):
        return [_redact_sensitive_values(item, depth + 1) for item in data]
    elif isinstance(data, str):
        from app.tools.github_tool import clean_workflow_log

        # Redact inline token patterns (very basic)
        if any(pattern in data for pattern in ["ghp_", "gho_", "ghu_", "ghs_", "ghr_", "sk-", "sk_"]):
            return "[REDACTED]"
        return clean_workflow_log(data)
    return data


async def log_execution(
    db: AsyncSession,
    *,
    tool_name: str,
    action_summary: str,
    status: str = "completed",
    actor: str = "system",
    tool_input: dict | None = None,
    tool_output: dict | None = None,
    error: str | None = None,
    session_id: str | None = None,
    source: str = "api",
) -> Execution:
    """
    Create an audit log entry for any CI/CD operation.

    Args:
        db: Async database session
        tool_name: Name of the tool/operation (e.g., "github_workflow_download", "failure_prediction")
        action_summary: Human-readable summary of what was done
        status: "completed", "failed", "pending"
        actor: Username or system identifier who triggered the action
        tool_input: Dict of input parameters (will be redacted)
        tool_output: Dict of output (will be redacted)
        error: Error message if status is "failed"
        session_id: Associated chat/session ID if available
        source: "api", "webhook", "agent", "system"

    Returns:
        The created Execution record
    """
    now = datetime.now(tz=timezone.utc)

    # Redact sensitive values from input and output
    redacted_input = _redact_sensitive_values(tool_input or {})
    redacted_output = _redact_sensitive_values(tool_output or {})

    # Build details dict with complete operation context
    details = {
        "input": redacted_input,
        "output": redacted_output,
        "source": source,
    }
    if error:
        details["error"] = error

    try:
        execution = Execution(
            id=str(uuid.uuid4()),
            session_id=session_id,
            requested_by=actor,
            tool_name=tool_name,
            tool_input=json.dumps(redacted_input, ensure_ascii=False, default=str),
            status=status,
            summary=action_summary,
            details=json.dumps(details, ensure_ascii=False, default=str),
            source=source,
            started_at=now,
            completed_at=now,
        )
        db.add(execution)
        await db.flush()

        # Log the operation for monitoring
        log_context = {
            "tool": tool_name,
            "status": status,
            "actor": actor,
            "source": source,
        }
        if error:
            logger.warning("execution.recorded_with_error", **log_context, error=error)
        else:
            logger.info("execution.recorded", **log_context)

        return execution
    except Exception as exc:
        logger.error(
            "audit.execution_creation_failed",
            tool_name=tool_name,
            error_type=exc.__class__.__name__,
            error=str(exc),
        )
        raise AuditError(f"Failed to create audit record: {exc}") from exc


async def log_prediction(
    db: AsyncSession,
    *,
    log_text: str,
    predicted_label: str,
    confidence: float | None = None,
    suggested_fix: str | None = None,
    actor: str = "system",
    session_id: str | None = None,
    source: str = "api",
) -> Execution:
    """Log an ML model prediction."""
    return await log_execution(
        db,
        tool_name="failure_prediction_model",
        action_summary=f"Predicted {predicted_label} (confidence={confidence})",
        status="completed",
        actor=actor,
        tool_input={
            "log_length": len(log_text),
            "log_first_500_chars": log_text[:500] if log_text else None,
        },
        tool_output={
            "label": predicted_label,
            "confidence": confidence,
            "suggested_fix": suggested_fix,
        },
        session_id=session_id,
        source=source,
    )


async def log_repo_analysis(
    db: AsyncSession,
    *,
    repo_full_name: str,
    files_analyzed: int,
    detected_stack: Mapping[str, Any] | None = None,
    actor: str = "system",
    session_id: str | None = None,
    source: str = "api",
) -> Execution:
    """Log repository stack detection."""
    return await log_execution(
        db,
        tool_name="repository_analyzer",
        action_summary=f"Analyzed {files_analyzed} files from {repo_full_name}",
        status="completed",
        actor=actor,
        tool_input={
            "repo": repo_full_name,
            "file_count": files_analyzed,
        },
        tool_output=dict(detected_stack or {}),
        session_id=session_id,
        source=source,
    )


async def log_workflow_generation(
    db: AsyncSession,
    *,
    repo_full_name: str,
    detected_stack: Mapping[str, Any] | None = None,
    workflow_template_name: str | None = None,
    actor: str = "system",
    session_id: str | None = None,
    source: str = "api",
) -> Execution:
    """Log GitHub Actions workflow generation."""
    return await log_execution(
        db,
        tool_name="workflow_generator",
        action_summary=f"Generated {workflow_template_name or 'custom'} workflow for {repo_full_name}",
        status="completed",
        actor=actor,
        tool_input={
            "repo": repo_full_name,
            "stack": dict(detected_stack or {}),
        },
        tool_output={
            "template": workflow_template_name,
            "path": ".github/workflows/ai-generated-ci.yml",
        },
        session_id=session_id,
        source=source,
    )


async def log_log_download(
    db: AsyncSession,
    *,
    repo_full_name: str,
    run_id: int,
    log_length: int,
    status: str = "completed",
    error: str | None = None,
    actor: str = "system",
    source: str = "webhook",
) -> Execution:
    """Log GitHub Actions logs download."""
    return await log_execution(
        db,
        tool_name="github_log_downloader",
        action_summary=f"Downloaded logs for {repo_full_name} run {run_id}",
        status=status,
        actor=actor,
        tool_input={
            "repo": repo_full_name,
            "run_id": run_id,
        },
        tool_output={
            "log_length": log_length,
        },
        error=error,
        source=source,
    )


async def log_workflow_pr_creation(
    db: AsyncSession,
    *,
    repo_full_name: str,
    branch: str,
    pull_request_url: str | None,
    status: str = "completed",
    error: str | None = None,
    actor: str = "system",
    session_id: str | None = None,
    source: str = "api",
) -> Execution:
    """Log workflow PR creation."""
    summary = f"Created PR for {repo_full_name}"
    if error:
        summary = f"Failed to create PR: {error[:100]}"

    return await log_execution(
        db,
        tool_name="github_workflow_pr",
        action_summary=summary,
        status=status,
        actor=actor,
        tool_input={
            "repo": repo_full_name,
            "branch": branch,
        },
        tool_output={
            "pull_request_url": pull_request_url,
        },
        error=error,
        session_id=session_id,
        source=source,
    )


async def log_fix_recommendation(
    db: AsyncSession,
    *,
    failure_label: str,
    recommendation: dict | None = None,
    actor: str = "system",
    session_id: str | None = None,
    source: str = "api",
) -> Execution:
    """Log fix recommendation lookup."""
    return await log_execution(
        db,
        tool_name="fix_recommendation",
        action_summary=f"Generated recommendation for {failure_label}",
        status="completed",
        actor=actor,
        tool_input={
            "failure_label": failure_label,
        },
        tool_output=recommendation or {},
        session_id=session_id,
        source=source,
    )


async def log_fix_pr_creation(
    db: AsyncSession,
    *,
    repo_full_name: str,
    workflow_failure_id: str,
    failure_label: str,
    pull_request_url: str | None,
    status: str = "completed",
    error: str | None = None,
    actor: str = "system",
    session_id: str | None = None,
) -> Execution:
    """Log fix pull request creation."""
    summary = f"Created fix PR for {repo_full_name} failure {failure_label}"
    if error:
        summary = f"Failed to create fix PR: {error[:100]}"

    return await log_execution(
        db,
        tool_name="github_fix_pr",
        action_summary=summary,
        status=status,
        actor=actor,
        tool_input={
            "repo": repo_full_name,
            "workflow_failure_id": workflow_failure_id,
            "failure_label": failure_label,
        },
        tool_output={
            "pull_request_url": pull_request_url,
        },
        error=error,
        session_id=session_id,
        source="api",
    )


async def log_approval_decision(
    db: AsyncSession,
    *,
    approval_id: str,
    decision: str,
    tool_name: str,
    actor: str = "system",
    session_id: str | None = None,
    reason: str | None = None,
) -> Execution:
    """Log approval decision (approve/reject)."""
    return await log_execution(
        db,
        tool_name="approval_decision",
        action_summary=f"{decision.capitalize()} approval request {approval_id}",
        status="completed",
        actor=actor,
        tool_input={
            "approval_id": approval_id,
            "original_tool": tool_name,
        },
        tool_output={
            "decision": decision,
            "reason": reason,
        },
        session_id=session_id,
        source="api",
    )


async def log_multi_agent_execution(
    db: AsyncSession,
    *,
    message: str,
    context: Mapping[str, Any] | None,
    selected_agent: str,
    intent: str,
    risk_level: str,
    success: bool,
    result: str,
    metadata: Mapping[str, Any] | None = None,
    actor: str = "system",
    user_id: str | None = None,
    session_id: str | None = None,
    source: str = "api",
) -> Execution:
    """Log a deterministic multi-agent orchestration run."""
    summarized_metadata = _summarize_agent_metadata(metadata)
    tool_or_service = (
        summarized_metadata.get("tool_called")
        or summarized_metadata.get("service_called")
        or summarized_metadata.get("proposed_tool_call")
        or selected_agent
    )
    approval_required = bool(summarized_metadata.get("approval_required"))
    status = "pending" if approval_required else "completed" if success else "failed"
    result_summary = _truncate_text(result or "", MAX_AUDIT_TEXT_LENGTH)
    error = result_summary if not success and not approval_required else None

    return await log_execution(
        db,
        tool_name="multi_agent_orchestration",
        action_summary=f"Routed request to {selected_agent} for {intent}",
        status=status,
        actor=actor,
        tool_input={
            "request_received": True,
            "message": _truncate_text(message or "", 500),
            "context": _summarize_context(context),
            "user_id": user_id,
        },
        tool_output={
            "selected_agent": selected_agent,
            "intent": intent,
            "risk_level": risk_level,
            "tool_or_service_called": tool_or_service,
            "success": success,
            "result_summary": result_summary,
            "metadata": summarized_metadata,
        },
        error=error,
        session_id=session_id,
        source=source,
    )
