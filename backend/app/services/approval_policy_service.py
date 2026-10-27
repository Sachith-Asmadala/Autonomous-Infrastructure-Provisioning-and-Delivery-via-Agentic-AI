"""Ownership and tool authorization for shared and personal HITL reviews."""
from fastapi import Depends, HTTPException

from app.core.security import get_current_user, has_permission
from app.models.models import ApprovalRequest
from app.schemas.schemas import ApprovalRequestOut
from app.services.activity_visibility_service import activity_actor

# Personal approval never grants a tool that requires elevated operational
# access. CI/CD PRs still execute through the existing branch/PR services.
_PERSONAL_APPROVAL_PERMISSIONS = {
    "github_create_workflow_pr": "repositories:write",
    "github_create_fix_pr": "repositories:write",
    "docker_restart_container": "deployments:staging",
}


def can_review_shared_approvals(current_user: dict) -> bool:
    return has_permission(current_user.get("role"), "approvals:decide")


async def require_approval_reviewer(current_user: dict = Depends(get_current_user)) -> dict:
    if not (can_review_shared_approvals(current_user)
            or has_permission(current_user.get("role"), "approvals:decide:own")):
        raise HTTPException(status_code=403, detail="Approval decision permission required.")
    return current_user


def can_decide_approval(current_user: dict, record: ApprovalRequest, *, approved: bool) -> bool:
    role = current_user.get("role")
    if record.tool_name == "admin_set_user_active" and not has_permission(role, "users:manage"):
        return False
    if can_review_shared_approvals(current_user):
        return True
    if (not has_permission(role, "approvals:decide:own")
            or record.requested_by != activity_actor(current_user)):
        return False
    if not approved:
        return True  # Members may cancel their own pending operational request.
    permission = _PERSONAL_APPROVAL_PERMISSIONS.get(record.tool_name or "")
    return bool(permission and has_permission(role, permission))


def approval_response(record: ApprovalRequest, current_user: dict) -> ApprovalRequestOut:
    pending = record.status == "pending"
    return ApprovalRequestOut.model_validate(record).model_copy(update={
        "can_approve": pending and can_decide_approval(current_user, record, approved=True),
        "can_reject": pending and can_decide_approval(current_user, record, approved=False),
    })
