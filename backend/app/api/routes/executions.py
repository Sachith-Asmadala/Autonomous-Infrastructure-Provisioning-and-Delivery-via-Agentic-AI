"""Execution history endpoints."""
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.database import get_db
from app.core.security import require_permission
from app.models.models import Execution
from app.schemas.schemas import ExecutionOut
from app.services.activity_visibility_service import activity_actor, can_view_all_activity
from app.services.execution_service import execution_response

router = APIRouter()


@router.get("", response_model=list[ExecutionOut])
@router.get("/", response_model=list[ExecutionOut], include_in_schema=False)
async def list_executions(
    limit: int = 50,
    tool: str | None = None,
    status: str | None = None,
    actor: str | None = None,
    source: str | None = None,
    days: int = 7,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("executions:read")),
):
    """
    List recent executions owned by the member, or all activity for admins.

    Query Parameters:
    - limit: Max results (default 50, max 200)
    - tool: Filter by tool name (e.g., "failure_prediction_model", "github_workflow_pr")
    - status: Filter by status (completed, failed, pending)
    - actor: Filter by actor/user (cannot override member ownership)
    - source: Filter by source (api, webhook, agent, system)
    - days: Look back N days (default 7)
    """
    filters: list[Any] = []

    # Apply ownership before optional filters. A supplied actor cannot broaden
    # a member's access, and both /audit and /executions use these rules.
    if not can_view_all_activity(current_user):
        filters.append(Execution.requested_by == activity_actor(current_user))

    if tool:
        filters.append(Execution.tool_name.ilike(f"%{tool}%"))
    if status:
        normalized_status = "completed" if status == "success" else status
        filters.append(Execution.status == normalized_status)
    if actor:
        filters.append(Execution.requested_by == actor)
    if source:
        filters.append(Execution.source == source)

    # Filter by date range
    cutoff_date = datetime.now(tz=timezone.utc)
    if days and days > 0:
        from datetime import timedelta

        cutoff_date = cutoff_date - timedelta(days=days)
        filters.append(Execution.started_at >= cutoff_date)

    where_clause = and_(*filters) if filters else true()

    stmt = (
        select(Execution)
        .options(joinedload(Execution.approval))
        .where(where_clause)
        .order_by(Execution.started_at.desc())
        .limit(min(limit, 200))
    )
    result = await db.execute(stmt)
    return [execution_response(record) for record in result.scalars().all()]


@router.get("/{execution_id}", response_model=ExecutionOut)
async def get_execution(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("executions:read")),
):
    """Read an owned execution; admins may read any execution."""
    stmt = select(Execution).options(joinedload(Execution.approval)).where(Execution.id == str(execution_id))
    if not can_view_all_activity(current_user):
        stmt = stmt.where(Execution.requested_by == activity_actor(current_user))
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Execution not found.")
    return execution_response(record)
