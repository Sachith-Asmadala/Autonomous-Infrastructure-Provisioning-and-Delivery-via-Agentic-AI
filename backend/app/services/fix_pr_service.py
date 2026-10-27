"""Safe fix pull request generation for diagnosed workflow failures."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import ApprovalRequest, Execution, WorkflowFailure
from app.services import audit_service
from app.services.fix_recommendation_service import get_fix_recommendation
from app.services.github_app_service import GitHubAppError, get_installation_access_token, get_installation_for_repo
from app.tools import github_tool

FIX_BRANCH_PREFIX = "ai-cicd/fix"
WORKFLOW_CANDIDATE_PATHS = (
    ".github/workflows/ai-generated-ci.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/ci.yaml",
    ".github/workflows/build.yml",
    ".github/workflows/build.yaml",
    ".github/workflows/test.yml",
    ".github/workflows/test.yaml",
)


class FixPRServiceError(RuntimeError):
    """Raised when a safe fix pull request cannot be generated."""


def _actor_name(current_user: dict | None) -> str:
    if not current_user:
        return "system"
    return str(current_user.get("username") or current_user.get("sub") or "unknown")


def _workflow_name_candidates(workflow_name: str | None) -> list[str]:
    if not workflow_name:
        return []
    slug = re.sub(r"[^a-z0-9]+", "-", workflow_name.lower()).strip("-")
    if not slug:
        return []
    return [f".github/workflows/{slug}.yml", f".github/workflows/{slug}.yaml"]


def _ordered_workflow_paths(workflow_name: str | None) -> list[str]:
    paths: list[str] = []
    for path in [*_workflow_name_candidates(workflow_name), *WORKFLOW_CANDIDATE_PATHS]:
        if path not in paths:
            paths.append(path)
    return paths


def _patch_npm_missing_test_script(content: str) -> tuple[str, str | None]:
    pattern = re.compile(r"(?<![\w-])npm\s+test(?!\s+--if-present)(?![\w-])")
    patched, replacements = pattern.subn("npm test --if-present", content)
    if replacements:
        return patched, "Changed npm test to npm test --if-present in the workflow."
    return content, None


def _patch_npm_missing_lockfile(content: str) -> tuple[str, str | None]:
    pattern = re.compile(r"(?<![\w-])npm\s+ci(?![\w-])")
    patched, replacements = pattern.subn("npm install", content)
    if replacements:
        return patched, "Changed npm ci to npm install in the workflow."
    return content, None


def _patch_pytest_not_found(content: str) -> tuple[str, str | None]:
    if re.search(r"\b(?:python\s+-m\s+)?pip\s+install\s+pytest\b", content):
        return content, None

    lines = content.splitlines()
    patched_lines: list[str] = []
    changed = False

    for line in lines:
        stripped = line.strip()

        dash_run = re.match(r"^(\s*)-\s*run:\s*(pytest\b.*)$", line)
        if dash_run and not changed:
            indent, command = dash_run.groups()
            patched_lines.extend(
                [
                    f"{indent}- run: |",
                    f"{indent}    python -m pip install pytest",
                    f"{indent}    {command}",
                ]
            )
            changed = True
            continue

        run_line = re.match(r"^(\s*)run:\s*(pytest\b.*)$", line)
        if run_line and not changed:
            indent, command = run_line.groups()
            patched_lines.extend(
                [
                    f"{indent}run: |",
                    f"{indent}  python -m pip install pytest",
                    f"{indent}  {command}",
                ]
            )
            changed = True
            continue

        if re.match(r"^pytest\b", stripped) and not changed:
            indent = line[: len(line) - len(line.lstrip())]
            patched_lines.append(f"{indent}python -m pip install pytest")
            changed = True

        patched_lines.append(line)

    if changed:
        trailing_newline = "\n" if content.endswith("\n") else ""
        return "\n".join(patched_lines) + trailing_newline, "Installed pytest before running pytest."
    return content, None


PATCHERS: dict[str, Callable[[str], tuple[str, str | None]]] = {
    "npm_missing_test_script": _patch_npm_missing_test_script,
    "npm_missing_lockfile": _patch_npm_missing_lockfile,
    "pytest_not_found": _patch_pytest_not_found,
}


def _github_kwargs(token: str | None) -> dict[str, str]:
    return {"token": token} if token else {}


async def _github_auth_for_repo(db: AsyncSession, repo_full_name: str) -> tuple[str | None, str, int | None]:
    """Return a token override plus safe auth-mode metadata for GitHub writes."""
    installation = await get_installation_for_repo(db, repo_full_name)
    if not installation:
        return None, "pat_fallback", None
    return (
        get_installation_access_token(installation.installation_id),
        "github_app_installation",
        int(installation.installation_id),
    )


def _recommendation_only(
    failure: WorkflowFailure,
    message: str,
    *,
    workflow_path: str | None = None,
) -> dict:
    recommendation = failure.recommendation or get_fix_recommendation(
        failure.predicted_label or "unknown_failure",
        failure.log_excerpt or "",
    )
    return {
        "workflow_failure_id": failure.id,
        "repo_full_name": failure.repo_full_name,
        "status": "recommendation_only",
        "branch": None,
        "workflow_path": workflow_path,
        "pull_request_url": None,
        "message": message,
        "recommendation": recommendation,
    }


def _risk_level(failure: WorkflowFailure) -> str:
    recommendation = failure.recommendation or get_fix_recommendation(
        failure.predicted_label or "unknown_failure",
        failure.log_excerpt or "",
    )
    risk = str(recommendation.get("risk_level") or "medium").lower()
    return risk if risk in {"low", "medium", "high", "critical"} else "medium"


def _approval_details(
    failure: WorkflowFailure,
    *,
    risk_level: str,
    proposed_file_changes: list[str] | None = None,
    workflow_path: str | None = None,
) -> dict:
    recommendation = failure.recommendation or get_fix_recommendation(
        failure.predicted_label or "unknown_failure",
        failure.log_excerpt or "",
    )
    changes = proposed_file_changes or recommendation.get("recommended_changes") or []
    if not changes:
        changes = ["No automatic file patch is available; review the recommendation manually."]
    return {
        "repository": failure.repo_full_name,
        "workflow_run_id": failure.workflow_run_id,
        "workflow_name": failure.workflow_name,
        "branch": failure.branch,
        "workflow_url": failure.workflow_url,
        "predicted_failure": failure.predicted_label or "unknown_failure",
        "confidence": failure.confidence,
        "suggested_fix": failure.suggested_fix,
        "proposed_file_changes": changes,
        "workflow_path": workflow_path,
        "risk_level": risk_level,
        "workflow_failure_id": failure.id,
    }


async def _create_fix_pr_approval(
    db: AsyncSession,
    *,
    failure: WorkflowFailure,
    actor: str,
    risk_level: str,
) -> dict:
    details = _approval_details(failure, risk_level=risk_level)
    pending = (await db.execute(select(ApprovalRequest).where(
        ApprovalRequest.tool_name == "github_create_fix_pr", ApprovalRequest.requested_by == actor,
        ApprovalRequest.status == "pending",
    ).order_by(ApprovalRequest.created_at.desc()))).scalars().all()
    # Pending requests remain reviewable; repeated clicks must not create a
    # second action for the same failure. Check its saved input, not UI state.
    for existing in pending:
        try:
            same_failure = json.loads(existing.tool_input or "{}").get("workflow_failure_id") == failure.id
        except (ValueError, AttributeError):
            continue
        expires_at = existing.expires_at
        unexpired = expires_at is None or expires_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
        if same_failure and unexpired:
            return {
                "workflow_failure_id": failure.id, "repo_full_name": failure.repo_full_name,
                "status": "approval_required", "approval_id": existing.id,
                "message": "This fix already has a pending approval request.",
                "recommendation": failure.recommendation, "approval_details": details,
            }
    summary = (
        f"Approve fix PR for {failure.repo_full_name} workflow run "
        f"{failure.workflow_run_id} ({failure.predicted_label or 'unknown_failure'})."
    )
    tool_input = {
        "workflow_failure_id": failure.id,
        "approval_details": details,
    }
    approval = ApprovalRequest(
        id=str(uuid.uuid4()),
        requested_by=actor,
        tool_name="github_create_fix_pr",
        tool_input=json.dumps(tool_input, ensure_ascii=False),
        payload=json.dumps(tool_input, ensure_ascii=False),
        action="Create GitHub fix pull request for diagnosed workflow failure",
        risk_level=risk_level,
        summary=summary,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.HITL_APPROVAL_TIMEOUT_SECONDS),
    )
    db.add(approval)
    failure.status = "approval_pending"
    failure.updated_at = datetime.now(tz=timezone.utc)
    await db.flush()
    await db.refresh(approval)

    result = {
        "workflow_failure_id": failure.id,
        "repo_full_name": failure.repo_full_name,
        "status": "approval_required",
        "approval_id": approval.id,
        "branch": None,
        "workflow_path": None,
        "pull_request_url": None,
        "message": "Human approval is required before creating this fix pull request.",
        "recommendation": failure.recommendation,
        "approval_details": details,
    }
    await _audit(
        db,
        actor=actor,
        status="pending",
        summary=f"Pending approval for fix PR on workflow failure {failure.id}",
        details={"tool_input": tool_input, "approval_id": approval.id, "result": result},
    )
    return result


async def _audit(
    db: AsyncSession,
    *,
    actor: str,
    status: str,
    summary: str,
    details: dict,
) -> Execution:
    now = datetime.now(tz=timezone.utc)
    execution = Execution(
        id=str(uuid.uuid4()),
        requested_by=actor,
        tool_name="github_create_fix_pr",
        tool_input=json.dumps(details.get("tool_input", {}), ensure_ascii=False),
        status=status,
        summary=summary,
        details=json.dumps(details, ensure_ascii=False),
        source="api",
        started_at=now,
        completed_at=now,
    )
    db.add(execution)
    await db.flush()
    return execution


def _read_workflow_file(
    repo_full_name: str,
    workflow_name: str | None,
    base_branch: str,
    *,
    token: str | None = None,
) -> dict | None:
    last_error: github_tool.GitHubToolError | None = None
    for path in _ordered_workflow_paths(workflow_name):
        try:
            return github_tool.get_file_content(repo_full_name, path, base_branch, **_github_kwargs(token))
        except github_tool.GitHubToolError as exc:
            if "not found" in str(exc).lower():
                last_error = exc
                continue
            raise
    if last_error:
        return None
    return None


def _branch_name(failure: WorkflowFailure) -> str:
    run_id = failure.workflow_run_id or "unknown"
    return f"{FIX_BRANCH_PREFIX}-{run_id}"


def _pr_body(failure: WorkflowFailure, workflow_path: str, change_summary: str) -> str:
    return (
        "This PR applies a low-risk CI/CD workflow fix suggested by the Smart DevOps Assistant.\n\n"
        f"- Repository: `{failure.repo_full_name}`\n"
        f"- Workflow run: `{failure.workflow_run_id}`\n"
        f"- Predicted failure: `{failure.predicted_label or 'unknown_failure'}`\n"
        f"- Workflow file: `{workflow_path}`\n"
        f"- Change: {change_summary}\n\n"
        "Safety notes:\n"
        "- The fix is limited to the workflow file.\n"
        "- No direct commit was made to main/master.\n"
        "- Please review the workflow diff before merging."
    )


async def create_fix_pr_for_failure(
    db: AsyncSession,
    workflow_failure_id: str | int,
    current_user: dict | None = None,
    *,
    bypass_approval: bool = False,
    audit: bool = True,
) -> dict:
    """Create a pull request with a low-risk workflow fix for a stored failure."""
    actor = _actor_name(current_user)
    failure = await db.get(WorkflowFailure, str(workflow_failure_id))
    if not failure:
        raise FixPRServiceError("Workflow failure diagnosis not found.")

    audit_input = {
        "workflow_failure_id": failure.id,
        "repo_full_name": failure.repo_full_name,
        "workflow_run_id": failure.workflow_run_id,
        "predicted_label": failure.predicted_label,
    }

    risk_level = _risk_level(failure)
    if failure.fix_pr_url:
        result: dict[str, Any] = {
            "workflow_failure_id": failure.id,
            "repo_full_name": failure.repo_full_name,
            "status": "already_created",
            "branch": None,
            "workflow_path": None,
            "pull_request_url": failure.fix_pr_url,
            "message": "A fix pull request is already linked to this workflow failure.",
            "recommendation": failure.recommendation,
        }
        if audit:
            await _audit(
                db,
                actor=actor,
                status="completed",
                summary=f"Fix PR already exists for workflow failure {failure.id}",
                details={"tool_input": audit_input, "result": result},
            )
        return result

    if not bypass_approval:
        return await _create_fix_pr_approval(
            db, failure=failure, actor=actor,
            risk_level=risk_level if risk_level in {"medium", "high", "critical"} else "medium",
        )

    if failure.predicted_label not in PATCHERS:
        result = _recommendation_only(
            failure,
            (
                "This failure type is not approved for automatic fixes yet. "
                "Review the recommendation before changing files."
            ),
        )
        if audit:
            await _audit(
                db,
                actor=actor,
                status="completed",
                summary=f"Recommendation only for workflow failure {failure.id}",
                details={"tool_input": audit_input, "result": result},
            )
        return result

    try:
        token, auth_mode, installation_id = await _github_auth_for_repo(db, failure.repo_full_name)
        base_branch = github_tool.get_default_branch(failure.repo_full_name, **_github_kwargs(token))
        workflow_file = _read_workflow_file(failure.repo_full_name, failure.workflow_name, base_branch, token=token)
        if workflow_file is None:
            result = _recommendation_only(
                failure,
                "No known GitHub Actions workflow file was found, so no repository files were modified.",
            )
            if audit:
                await _audit(
                    db,
                    actor=actor,
                    status="completed",
                    summary=f"No workflow file found for workflow failure {failure.id}",
                    details={"tool_input": audit_input, "result": result},
                )
            return result

        patcher = PATCHERS[failure.predicted_label or ""]
        patched_content, change_summary = patcher(workflow_file["content"])
        if not change_summary or patched_content == workflow_file["content"]:
            result = _recommendation_only(
                failure,
                "The workflow file did not contain a safe, recognizable pattern to patch.",
                workflow_path=workflow_file["path"],
            )
            if audit:
                await _audit(
                    db,
                    actor=actor,
                    status="completed",
                    summary=f"No safe patch available for workflow failure {failure.id}",
                    details={"tool_input": audit_input, "result": result},
                )
            return result

        branch = _branch_name(failure)
        try:
            branch_result = github_tool.create_branch(
                failure.repo_full_name,
                base_branch,
                branch,
                **_github_kwargs(token),
            )
        except github_tool.GitHubToolError as exc:
            if "already exists" not in str(exc).lower():
                raise
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            branch = f"{branch}-{timestamp}"
            branch_result = github_tool.create_branch(
                failure.repo_full_name,
                base_branch,
                branch,
                **_github_kwargs(token),
            )

        file_result = github_tool.create_or_update_file(
            failure.repo_full_name,
            branch,
            workflow_file["path"],
            patched_content,
            f"Apply safe CI fix for run {failure.workflow_run_id}",
            overwrite=True,
            **_github_kwargs(token),
        )
        pr_result = github_tool.create_pull_request(
            failure.repo_full_name,
            branch,
            base_branch,
            f"Fix CI workflow failure for run {failure.workflow_run_id}",
            _pr_body(failure, workflow_file["path"], change_summary),
            **_github_kwargs(token),
        )

        failure.fix_pr_url = pr_result["html_url"]
        failure.status = "fix_pr_created"
        failure.updated_at = datetime.now(tz=timezone.utc)

        result = {
            "workflow_failure_id": failure.id,
            "repo_full_name": failure.repo_full_name,
            "status": "fix_pr_created",
            "auth_mode": auth_mode,
            "branch": branch,
            "workflow_path": workflow_file["path"],
            "pull_request_url": pr_result["html_url"],
            "message": change_summary,
            "recommendation": failure.recommendation,
            "file": file_result,
            "branch_result": branch_result,
        }
        if installation_id is not None:
            result["installation_id"] = installation_id
        if audit:
            await _audit(
                db,
                actor=actor,
                status="completed",
                summary=f"Created fix PR for workflow failure {failure.id}: {pr_result['html_url']}",
                details={"tool_input": audit_input, "result": result},
            )
            await audit_service.log_fix_pr_creation(
                db,
                repo_full_name=failure.repo_full_name,
                workflow_failure_id=failure.id,
                failure_label=failure.predicted_label or "unknown_failure",
                pull_request_url=pr_result["html_url"],
                actor=actor,
            )
        await db.flush()
        await db.refresh(failure)
        return result
    except (github_tool.GitHubToolError, GitHubAppError) as exc:
        failure.status = "fix_pr_failed"
        failure.updated_at = datetime.now(tz=timezone.utc)
        if audit:
            await _audit(
                db,
                actor=actor,
                status="failed",
                summary=f"Failed to create fix PR for workflow failure {failure.id}",
                details={"tool_input": audit_input, "error": str(exc)},
            )
            await audit_service.log_fix_pr_creation(
                db,
                repo_full_name=failure.repo_full_name,
                workflow_failure_id=failure.id,
                failure_label=failure.predicted_label or "unknown_failure",
                pull_request_url=None,
                status="failed",
                error=str(exc),
                actor=actor,
            )
        await db.flush()
        raise FixPRServiceError(str(exc)) from exc


async def mark_fix_pr_rejected(
    db: AsyncSession,
    workflow_failure_id: str | int,
    *,
    decided_by: str,
    note: str | None = None,
) -> WorkflowFailure | None:
    """Mark a workflow failure fix PR request as rejected by a human reviewer."""
    failure = await db.get(WorkflowFailure, str(workflow_failure_id))
    if not failure:
        return None
    failure.status = "rejected"
    failure.updated_at = datetime.now(tz=timezone.utc)
    await db.flush()
    return failure
