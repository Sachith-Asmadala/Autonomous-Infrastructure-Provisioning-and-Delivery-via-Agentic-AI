"""
Execution service — creates and updates Execution rows in the DB.
Called by the agent after every tool invocation.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Execution
from app.schemas.schemas import ExecutionOut


def execution_response(record: Execution) -> ExecutionOut:
    """Include the reviewer separately from the action's original requester.

    The caller must eager-load the approval relationship to avoid implicit
    asynchronous database access during response serialization.
    """
    response = ExecutionOut.model_validate(record)
    if record.approval:
        response.approval_decided_by = record.approval.decided_by
        response.approval_status = record.approval.status
    return response


async def create_execution(
    db: AsyncSession,
    *,
    requested_by: str,
    summary: str,
    source: str = "agent",
    approval_id: str | None = None,
) -> Execution:
    """Insert a new Execution row and return it."""
    exc = Execution(
        requested_by=requested_by,
        status="running",
        summary=summary,
        source=source,
        approval_id=approval_id,
    )
    db.add(exc)
    await db.flush()
    await db.refresh(exc)
    return exc


async def complete_execution(
    db: AsyncSession,
    *,
    execution: Execution,
    output: str,
    intermediate_steps: list[Any] | None = None,
    success: bool = True,
) -> Execution:
    """Mark an execution as completed (or failed) and persist details."""
    execution.status = "completed" if success else "failed"
    execution.details = json.dumps(
        [str(step) for step in (intermediate_steps or [])],
        ensure_ascii=False,
    )
    execution.summary = output[:500]   # keep DB summary concise
    execution.completed_at = datetime.now(tz=timezone.utc)
    await db.flush()
    return execution
