"""Read GitHub failures or pasted logs and persist diagnoses with an owner."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.models.models import WorkflowFailure
from app.schemas.schemas import WorkflowFailureImportRequest, WorkflowFailureSyncRequest
from app.services import audit_service, failure_prediction_service
from app.services.activity_visibility_service import activity_actor
from app.services.github_app_service import get_installation_access_token, get_installation_for_repo
from app.services.workflow_failure_service import create_workflow_failure
from app.tools import github_tool


async def _existing(db: AsyncSession, repo: str, run_id: int, actor: str) -> WorkflowFailure | None:
    return await db.scalar(
        select(WorkflowFailure).where(
            WorkflowFailure.repo_full_name == repo,
            WorkflowFailure.workflow_run_id == run_id,
            WorkflowFailure.requested_by == actor,
        ).order_by(WorkflowFailure.created_at.desc()).limit(1)
    )


async def _diagnose(db: AsyncSession, record: WorkflowFailure, log_text: str, actor: str) -> None:
    log_text = github_tool.clean_workflow_log(log_text).strip()
    if not log_text:
        raise failure_prediction_service.FailurePredictionError("The workflow logs are empty.")
    prediction = await run_in_threadpool(failure_prediction_service.predict_failure, log_text)
    record.log_excerpt = log_text[:1500]
    record.predicted_label = prediction["label"]
    record.confidence = prediction.get("confidence")
    record.suggested_fix = prediction.get("suggested_fix")
    record.recommendation_json = (
        json.dumps(prediction["recommendation"]) if prediction.get("recommendation") else None
    )
    record.diagnosis_error = None
    if record.status not in {"approval_pending", "fix_pr_created", "rejected"}:
        record.status = "diagnosed"
    record.updated_at = datetime.now(timezone.utc)
    await audit_service.log_prediction(
        db, log_text=log_text, predicted_label=prediction["label"], confidence=prediction.get("confidence"),
        suggested_fix=prediction.get("suggested_fix"), actor=actor, source="api",
    )
    if prediction.get("recommendation"):
        await audit_service.log_fix_recommendation(
            db, failure_label=prediction["label"], recommendation=prediction["recommendation"],
            actor=actor, source="api",
        )


async def import_workflow_failure(
    db: AsyncSession, request: WorkflowFailureImportRequest, current_user: dict,
) -> WorkflowFailure:
    actor = activity_actor(current_user)
    repo = github_tool._validate_repo_full_name(request.repo_full_name).lower()
    record = await _existing(db, repo, request.workflow_run_id, actor)
    if record is None:
        record = await create_workflow_failure(
            db, repo_full_name=repo, workflow_run_id=request.workflow_run_id,
            workflow_name=request.workflow_name, branch=request.branch, requested_by=actor,
            workflow_url=f"https://github.com/{repo}/actions/runs/{request.workflow_run_id}", status="pending",
        )
    await _diagnose(db, record, request.log_text, actor)
    await db.flush()
    await db.refresh(record)
    return record


async def sync_workflow_failures(
    db: AsyncSession, request: WorkflowFailureSyncRequest, current_user: dict,
) -> dict:
    actor = activity_actor(current_user)
    repo = github_tool._validate_repo_full_name(request.repo_full_name).lower()
    installation = await get_installation_for_repo(db, repo)
    token = (
        await run_in_threadpool(get_installation_access_token, installation.installation_id)
        if installation else None
    )
    runs = await run_in_threadpool(github_tool.list_failed_workflow_runs, repo, request.limit, token=token)
    records = []
    imported = 0
    for run in runs:
        run_id = int(run["id"])
        record = await _existing(db, repo, run_id, actor)
        if record is None:
            record = await create_workflow_failure(
                db, repo_full_name=repo, workflow_run_id=run_id, requested_by=actor,
                workflow_name=run.get("name"), branch=run.get("head_branch"),
                conclusion=run.get("conclusion") or "failure",
                workflow_url=f"https://github.com/{repo}/actions/runs/{run_id}", status="pending",
            )
            imported += 1
        # Repeated sync preserves completed diagnoses and approval/fix state.
        if not record.predicted_label:
            if not (token or settings.GITHUB_TOKEN):
                record.status = "logs_unavailable"
                record.diagnosis_error = (
                    "Automatic log download needs GitHub access. Paste this run’s logs to diagnose it."
                )
            else:
                try:
                    logs = await run_in_threadpool(github_tool.download_workflow_logs, repo, run_id, token=token)
                    await _diagnose(db, record, logs, actor)
                except (github_tool.GitHubToolError, failure_prediction_service.FailurePredictionError,
                        failure_prediction_service.FailurePredictionUnavailable) as exc:
                    record.status = "diagnosis_failed"
                    record.diagnosis_error = str(exc)
                    await audit_service.log_execution(
                        db, tool_name="workflow_failure_import",
                        action_summary=f"Diagnosis unavailable for {repo} run {run_id}",
                        status="failed", actor=actor, tool_input={"repo": repo, "run_id": run_id},
                        error=str(exc), source="api",
                    )
        records.append(record)
    await audit_service.log_execution(
        db, tool_name="workflow_failure_sync", action_summary=f"Loaded {len(records)} failed workflow runs from {repo}",
        status="completed", actor=actor, tool_input={"repo": repo, "limit": request.limit},
        tool_output={"imported": imported, "failed_runs": len(records)}, source="api",
    )
    await db.flush()
    for record in records:
        await db.refresh(record)
    diagnosed = sum(bool(record.predicted_label) for record in records)
    return {
        "failures": records, "imported": imported, "diagnosed": diagnosed,
        "message": (
            f"Loaded {len(records)} failed runs; {diagnosed} have a diagnosis."
            if records else "No failed runs found in this repository."
        ),
    }
