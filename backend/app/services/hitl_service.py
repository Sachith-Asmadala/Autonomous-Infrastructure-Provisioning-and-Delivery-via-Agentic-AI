"""
HITL (Human-in-the-Loop) service.

Flow
----
1. Agent classifies an action as HIGH or CRITICAL risk.
2. Agent calls ``create_approval_request()``.
3. An authorized reviewer calls POST /api/v1/approvals/{id}/decide.
4. ``decide_approval()`` updates the record and (if approved) resumes
   the pending tool call by returning the stored payload.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import ApprovalRequest


# ── Write ─────────────────────────────────────────────────────────────────────

async def create_approval_request(
    db: AsyncSession,
    *,
    requested_by: str,
    action: str,
    risk_level: str,
    summary: str,
    payload: dict | None = None,
) -> ApprovalRequest:
    """
    Persist a pending HITL approval request.

    ``payload`` stores the serialised tool-call arguments so the agent
    can resume execution after an approval decision.
    """
    req = ApprovalRequest(
        requested_by=requested_by,
        action=action,
        risk_level=risk_level,
        summary=summary,
        status="pending",
        payload=json.dumps(payload or {}, ensure_ascii=False),
    )
    db.add(req)
    await db.flush()
    await db.refresh(req)
    return req


async def decide_approval(
    db: AsyncSession,
    *,
    approval_id: str | UUID,
    approved: bool,
    decided_by: str,
    note: str | None = None,
) -> ApprovalRequest:
    """
    Record a reviewer's approve/reject decision.

    Returns the updated ApprovalRequest.  Raises 404 if not found,
    409 if already decided.
    """
    result = await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == str(approval_id))
    )
    req: ApprovalRequest | None = result.scalar_one_or_none()

    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval request '{approval_id}' not found.",
        )
    if req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Approval request is already '{req.status}'.",
        )

    req.status = "approved" if approved else "rejected"
    req.decided_by = decided_by
    req.decision_note = note
    req.decided_at = datetime.now(tz=timezone.utc)
    await db.flush()
    return req


# ── Read ──────────────────────────────────────────────────────────────────────

async def list_pending(db: AsyncSession) -> list[ApprovalRequest]:
    result = await db.execute(
        select(ApprovalRequest)
        .where(ApprovalRequest.status == "pending")
        .order_by(ApprovalRequest.created_at.desc())
    )
    return list(result.scalars().all())


async def list_all(db: AsyncSession, limit: int = 50) -> list[ApprovalRequest]:
    result = await db.execute(
        select(ApprovalRequest)
        .order_by(ApprovalRequest.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


def get_payload(req: ApprovalRequest) -> dict[str, Any]:
    """Deserialise the stored tool-call payload."""
    try:
        return json.loads(req.payload or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
