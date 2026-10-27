"""Pydantic request/response schemas."""
import uuid
from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.security import UserRole


class IntermediateStep(BaseModel):
    tool: str
    input: Any = ""
    output: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = Field(None, max_length=128)


class ChatResponse(BaseModel):
    output: str
    session_id: str
    intermediate_steps: List[IntermediateStep] = Field(default_factory=list)
    requires_approval: Optional[bool] = None
    approval_id: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=20)


class UserOut(BaseModel):
    id: str
    email: EmailStr
    username: str
    role: UserRole
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    role: str


class LoginResponse(TokenResponse):
    user: UserOut


class UserRegister(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)
    role: Optional[UserRole] = UserRole.DEVELOPER


class AdminCreateUser(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)
    role: Literal[UserRole.DEVELOPER] = UserRole.DEVELOPER
    is_active: bool = True


class UserStatusChangeRequest(BaseModel):
    is_active: bool


class UserStatusApprovalOut(BaseModel):
    approval_id: uuid.UUID
    user: UserOut
    is_active: bool
    status: Literal["approval_required"] = "approval_required"


class RoleProfile(BaseModel):
    role: UserRole
    label: str
    description: str
    permissions: list[str]
    can_self_signup: bool = False


class RolesResponse(BaseModel):
    roles: list[RoleProfile]
    public_signup_roles: list[UserRole]


class ApprovalDecision(BaseModel):
    approved: bool
    note: Optional[str] = None


class ApprovalRequestOut(BaseModel):
    id: uuid.UUID
    requested_by: str
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None
    payload: Optional[str] = None
    action: str
    risk_level: str
    summary: str
    status: str
    created_at: datetime
    expires_at: Optional[datetime] = None
    decided_by: Optional[str] = None
    decision_note: Optional[str] = None
    decided_at: Optional[datetime] = None
    can_approve: bool = False
    can_reject: bool = False

    model_config = ConfigDict(from_attributes=True)


class ExecutionOut(BaseModel):
    id: uuid.UUID
    requested_by: str
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None
    status: str
    summary: str
    details: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    source: Optional[str] = None
    approval_decided_by: Optional[str] = None
    approval_status: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class WorkflowFailureOut(BaseModel):
    id: uuid.UUID
    repo_full_name: str
    workflow_run_id: int
    requested_by: Optional[str] = None
    diagnosis_error: Optional[str] = None
    has_pending_approval: Optional[bool] = None
    workflow_name: Optional[str] = None
    branch: Optional[str] = None
    conclusion: str
    workflow_url: Optional[str] = None
    log_excerpt: Optional[str] = None
    predicted_label: Optional[str] = None
    confidence: Optional[float] = None
    suggested_fix: Optional[str] = None
    recommendation: Optional[dict[str, Any]] = None
    fix_pr_url: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class WorkflowFailureSyncRequest(BaseModel):
    repo_full_name: str = Field(min_length=3, max_length=255, pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    limit: int = Field(default=10, ge=1, le=20)


class WorkflowFailureImportRequest(BaseModel):
    repo_full_name: str = Field(min_length=3, max_length=255, pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    workflow_run_id: int = Field(gt=0, le=9223372036854775807)
    log_text: str = Field(min_length=1, max_length=200000)
    workflow_name: Optional[str] = Field(default=None, max_length=255)
    branch: Optional[str] = Field(default=None, max_length=255)


class WorkflowFailureSyncResponse(BaseModel):
    failures: list[WorkflowFailureOut]
    imported: int
    diagnosed: int
    message: str


class WorkflowFailureIntegrationStatus(BaseModel):
    can_download_logs: bool
    webhook_configured: bool
    default_repository: Optional[str] = None


class WorkflowFailureFixPRResponse(BaseModel):
    workflow_failure_id: uuid.UUID
    repo_full_name: str
    status: str
    approval_id: Optional[uuid.UUID] = None
    branch: Optional[str] = None
    workflow_path: Optional[str] = None
    pull_request_url: Optional[str] = None
    message: str
    recommendation: Optional[dict[str, Any]] = None
    approval_details: Optional[dict[str, Any]] = None


class FailurePredictionRequest(BaseModel):
    log_text: str = Field(default="", max_length=20000)


class FailurePredictionResponse(BaseModel):
    label: str
    confidence: Optional[float] = None
    suggested_fix: str
    recommendation: dict[str, Any]


class CICDAnalyzeFilesRequest(BaseModel):
    files: list[str] = Field(default_factory=list, max_length=5000)


class CICDStackResponse(BaseModel):
    language: str
    framework: str
    package_manager: str
    has_docker: bool
    has_existing_workflows: bool
    recommended_workflow: str
    project_dir: str = "."
    detected_projects: list[dict[str, Any]] = Field(default_factory=list)
    ci_warnings: list[dict[str, Any]] = Field(default_factory=list)


class CICDWorkflowResponse(BaseModel):
    stack: CICDStackResponse
    path: str
    workflow_yaml: str


class CICDReadinessReportResponse(BaseModel):
    score: int
    grade: str
    summary: str
    strengths: list[str] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    recommended_next_actions: list[str] = Field(default_factory=list)


class RepositoryScanRequest(BaseModel):
    repo_full_name: str = Field(..., min_length=3, max_length=255)
    branch: Optional[str] = Field(default=None, max_length=255)


class RepositoryScanResponse(BaseModel):
    repo_full_name: str
    files: list[str]
    stack: CICDStackResponse
    readiness: CICDReadinessReportResponse


class RepositoryInstallationOut(BaseModel):
    id: uuid.UUID
    installation_id: int
    repo_full_name: str
    owner: str
    repo: str
    default_branch: str
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class RepositoryWorkflowPRRequest(BaseModel):
    repo_full_name: str = Field(..., min_length=3, max_length=255)
    overwrite_existing_workflow: bool = False


class RepositoryWorkflowPRResponse(BaseModel):
    repo_full_name: str
    detected_stack: Optional[CICDStackResponse] = None
    branch: Optional[str] = None
    workflow_path: Optional[str] = None
    pull_request_url: Optional[str] = None
    status: Optional[str] = None
    approval_required: Optional[bool] = None
    approval_id: Optional[uuid.UUID] = None
    message: Optional[str] = None
    approval_status: Optional[str] = None
    expires_at: Optional[datetime] = None
    execution_id: Optional[uuid.UUID] = None
    execution_status: Optional[str] = None
