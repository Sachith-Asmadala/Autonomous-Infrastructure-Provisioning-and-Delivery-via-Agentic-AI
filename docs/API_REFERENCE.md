# API Reference — Smart DevOps Assistant

Base API prefix: `/api/v1`

**Interactive OpenAPI docs** are available at `/docs` when the backend is running.

---

## Table of Contents

1. [Authentication Model](#1-authentication-model)
2. [Roles and Permissions](#2-roles-and-permissions)
3. [Common Error Shape](#3-common-error-shape)
4. [Health Endpoints](#4-health-endpoints)
5. [Authentication Endpoints](#5-authentication-endpoints)
6. [Multi-Agent Orchestration](#6-multi-agent-orchestration)
7. [CI/CD Analysis & Workflow Generation](#7-cicd-analysis--workflow-generation)
8. [Repository Management](#8-repository-management)
9. [Failure Prediction](#9-failure-prediction)
10. [GitHub Webhooks](#10-github-webhooks)
11. [Workflow Failures](#11-workflow-failures)
12. [Approvals (Human-in-the-Loop)](#12-approvals-human-in-the-loop)
13. [Executions & Audit Logs](#13-executions--audit-logs)
14. [Evaluation & Metrics](#14-evaluation--metrics)
15. [Legacy Aliases](#15-legacy-aliases)

---

## 1. Authentication Model

The backend accepts access tokens from either:

- **Authorization Header**: `Authorization: Bearer <access_token>`
- **HTTP-Only Cookie**: default cookie name `devops_access_token`

Most browser-based clients use the cookie automatically. API clients (curl, SDKs) use bearer tokens.

**Public endpoints** (no authentication required):

- `GET /health`
- `GET /`
- `GET /api/v1/auth/roles`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/webhooks/github` (public HTTP, but requires valid `X-Hub-Signature-256` HMAC)

**All other routes** require a valid access token and the specified permission.

---

## 2. Roles and Permissions

| Role | Main Permissions | Use Case |
| --- | --- | --- |
| `developer` | CI/CD generation, repository workflow requests, own approvals, own execution history | Personal delivery workspace. |
| `admin` | All permissions | Full system access. |

- **Public sign-up**: Developer accounts only; the role field can be omitted.
- **Member creation**: Admin-only, via `POST /api/v1/auth/users`, for developer accounts. Creating additional admin accounts is disabled;
  the initial admin is bootstrapped when no administrator exists.

---

## 3. Common Error Shape

All error responses follow this format:

```json
{
  "detail": "Human-readable error message."
}
```

**Common status codes:**

| Code | Meaning |
| --- | --- |
| `400` | Bad request or external service validation failure. |
| `401` | Missing, invalid, or expired token. |
| `403` | Authenticated user lacks required permission. |
| `404` | Requested record not found. |
| `409` | Resource conflict (e.g., approval already decided). |
| `410` | Resource expired (e.g., approval timeout). |
| `422` | Request validation failed. |
| `429` | Rate limit exceeded or provider quota exceeded. |
| `500` | Unexpected backend error. |
| `503` | Required service unavailable (model, LLM provider, etc.). |

---

## 4. Health Endpoints

### `GET /health`

**Purpose**: Check backend health.

**Auth**: None.

**Response** (200 OK):

```json
{
  "status": "ok",
  "service": "Smart DevOps Assistant"
}
```

---

### `GET /`

**Purpose**: Root info endpoint.

**Auth**: None.

**Response** (200 OK):

```json
{
  "name": "Agentic AI-Powered Smart DevOps Assistant",
  "version": "1.0.0",
  "docs": "/docs"
}
```

---

## 5. Authentication Endpoints

### `GET /api/v1/auth/roles`

**Purpose**: List all available role profiles and public signup roles.

**Method**: GET | **Path**: `/api/v1/auth/roles`

**Auth**: None.

**Response** (200 OK):

```json
{
  "roles": [
    {
      "role": "admin",
      "label": "Admin",
      "description": "Full platform owner. Can manage users, audit activity, approve changes, and use all agent tools.",
      "permissions": [
        "*"
      ],
      "can_self_signup": false
    },
    {
      "role": "developer",
      "label": "Developer",
      "description": "Can build CI/CD workflows, review their own approval requests, and use development/staging tools.",
      "permissions": [
        "agent:chat",
        "agents:orchestrate",
        "approvals:decide:own",
        "approvals:read",
        "cicd:generate",
        "cicd:read",
        "deployments:staging",
        "executions:read",
        "failures:predict",
        "logs:read",
        "repositories:read",
        "repositories:write",
        "workflow_failures:read"
      ],
      "can_self_signup": true
    }
  ],
  "public_signup_roles": [
    "developer"
  ]
}
```

---

### `POST /api/v1/auth/register`

**Purpose**: Create a public developer account and log in.

**Method**: POST | **Path**: `/api/v1/auth/register`

**Auth**: None.

**Request** (200 OK):

```json
{
  "email": "dev@example.com",
  "username": "devuser",
  "password": "password123",
  "role": "developer"
}
```

**Response** (200 OK):

```json
{
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "dev@example.com",
    "username": "devuser",
    "role": "developer",
    "is_active": true,
    "created_at": "2026-06-01T10:00:00Z"
  },
  "access_token": "eyJhbGc...",
  "refresh_token": "eyJhbGc...",
  "token_type": "bearer",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "devuser",
  "role": "developer"
}
```

**Error** (400 Bad Request):

- Email already registered
- Username already taken
- Role not in public signup roles

---

### `POST /api/v1/auth/login`

**Purpose**: Authenticate and receive access/refresh tokens. Sets httpOnly cookie.

**Method**: POST | **Path**: `/api/v1/auth/login`

**Auth**: None.

**Request** (email or username):

```json
{
  "email": "dev@example.com",
  "password": "password123"
}
```

**Legacy Request** (username):

```json
{
  "username": "devuser",
  "password": "password123"
}
```

**Response** (200 OK):

```json
{
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "dev@example.com",
    "username": "devuser",
    "role": "developer",
    "is_active": true,
    "created_at": "2026-06-01T10:00:00Z"
  },
  "access_token": "eyJhbGc...",
  "refresh_token": "eyJhbGc...",
  "token_type": "bearer",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "devuser",
  "role": "developer"
}
```

**Notes**:
- Access token expires in ~15 minutes (configurable).
- httpOnly cookie `devops_access_token` is set automatically.
- Use refresh token to obtain a new access token before expiry.

---

### `POST /api/v1/auth/logout`

**Purpose**: Clear the access cookie and log out.

**Method**: POST | **Path**: `/api/v1/auth/logout`

**Auth**: Required, any authenticated user.

**Request**: (empty body)

**Response** (204 No Content)

---

### `POST /api/v1/auth/refresh`

**Purpose**: Exchange a valid refresh token for a new access/refresh pair.

**Method**: POST | **Path**: `/api/v1/auth/refresh`

**Auth**: None (uses refresh token in body).

**Request**:

```json
{
  "refresh_token": "eyJhbGc..."
}
```

**Response** (200 OK):

```json
{
  "access_token": "eyJhbGc...",
  "refresh_token": "eyJhbGc...",
  "token_type": "bearer"
}
```

---

### `GET /api/v1/auth/me`

**Purpose**: Fetch the current authenticated user's profile.

**Method**: GET | **Path**: `/api/v1/auth/me`

**Auth**: Required, any authenticated user.

**Response** (200 OK):

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "dev@example.com",
  "username": "devuser",
  "role": "developer",
  "is_active": true,
  "created_at": "2026-06-01T10:00:00Z"
}
```

---

### `GET /api/v1/auth/users`

**Purpose**: List all users in the system.

**Method**: GET | **Path**: `/api/v1/auth/users`

**Auth**: Required permission `users:manage` (admin only).

**Response** (200 OK):

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "admin@example.com",
    "username": "admin",
    "role": "admin",
    "is_active": true,
    "created_at": "2026-06-01T00:00:00Z"
  },
  {
    "id": "550e8400-e29b-41d4-a716-446655440001",
    "email": "member@example.com",
    "username": "member1",
    "role": "developer",
    "is_active": true,
    "created_at": "2026-06-01T08:30:00Z"
  }
]
```

---

### `POST /api/v1/auth/users`

**Purpose**: Create a new user account (admin-only operation).

Only `developer` is accepted. `admin` requests
return HTTP 422; existing administrator accounts are preserved.

**Method**: POST | **Path**: `/api/v1/auth/users`

**Auth**: Required permission `users:manage` (admin only).

**Request**:

```json
{
  "email": "member@example.com",
  "username": "member1",
  "password": "secure_password_123",
  "role": "developer",
  "is_active": true
}
```

**Response** (201 Created):

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440001",
  "email": "member@example.com",
  "username": "member1",
  "role": "developer",
  "is_active": true,
  "created_at": "2026-06-01T08:30:00Z"
}
```

**Error** (400 Bad Request):

- Email already registered
- Username already taken

---

## 6. Multi-Agent Orchestration

The orchestration layer routes natural language requests to specialized agents (GitHub, CI/CD, CLI, Diagnosis) with deterministic intent detection and approval gating.

### `POST /api/v1/agent/orchestrate`

**Purpose**: Route a request through the multi-agent orchestration layer with intent detection and approval gating.

**Method**: POST | **Path**: `/api/v1/agent/orchestrate`

**Auth**: Required permission `agent:chat`.

**Request**:

```json
{
  "message": "scan repository owner/demo-repo",
  "context": {
    "repo_full_name": "owner/demo-repo",
    "session_id": "optional-session-uuid"
  }
}
```

**Response - Low-Risk (200 OK):**

```json
{
  "selected_agent": "github_agent",
  "intent": "github_scan_repository",
  "risk_level": "low",
  "success": true,
  "result": "Repository owner/demo-repo scanned. Detected: Python/FastAPI with lockfile. 42 files analyzed.",
  "metadata": {
    "repo_full_name": "owner/demo-repo",
    "file_count": 42,
    "detected_stack": {
      "language": "python",
      "framework": "fastapi",
      "package_manager": "pip"
    }
  }
}
```

**Response - High-Risk (Approval Required, 200 OK):**

```json
{
  "selected_agent": "github_agent",
  "intent": "github_create_workflow_pr",
  "risk_level": "medium",
  "success": false,
  "result": "Human approval is required before executing this action. Approval request 12345... is pending.",
  "metadata": {
    "approval_required": true,
    "approval_id": "550e8400-e29b-41d4-a716-446655440099",
    "proposed_tool_call": "github_create_workflow_pr",
    "approval_details": {
      "summary": "Create AI-generated GitHub Actions workflow PR for owner/repo",
      "risk_level": "medium",
      "action": "Create GitHub Actions workflow pull request"
    }
  }
}
```

**Notes**:
- Specialized agents: `github_agent`, `cicd_agent`, `diagnosis_agent`, `cli_agent`.
- High-risk actions (workflow PR creation, fix PR creation) require approval when `ENABLE_HITL=true`.
- Approval timeout defaults to 300 seconds (5 minutes).

---

### `POST /api/v1/agent/chat` (Legacy)

**Purpose**: Chat with the legacy DevOps agent (LangChain-based).

**Method**: POST | **Path**: `/api/v1/agent/chat`

**Auth**: Required permission `agent:chat`.

**Request**:

```json
{
  "message": "What are the recent workflow runs?",
  "session_id": "optional-session-id"
}
```

**Response** (200 OK):

```json
{
  "output": "Recent workflow runs: 5 completed, 1 failed, 0 in progress.",
  "session_id": "session-uuid",
  "intermediate_steps": [
    {
      "tool": "github_list_recent_runs",
      "input": "{}",
      "output": "[...]"
    }
  ],
  "requires_approval": false,
  "approval_id": null
}
```

---

### `DELETE /api/v1/agent/session/{session_id}`

**Purpose**: Clear chat history and memory for a session.

**Method**: DELETE | **Path**: `/api/v1/agent/session/{session_id}`

**Auth**: Required permission `agent:chat`.

**Parameter**:
- `session_id` (UUID): Session to clear.

**Response** (204 No Content)

---

### WebSocket `/api/v1/agent/ws/agent`

**Purpose**: Stream agent responses in real-time.

**Method**: WebSocket | **Path**: `/api/v1/agent/ws/agent`

**Auth**: Token via cookie, bearer header, or `?token=<jwt>` query parameter.

**Legacy aliases**:
- `/api/agent/ws/agent`
- `/ws/agent`

**Notes**: Primarily used by the frontend for real-time chat streaming.

---

## 7. CI/CD Analysis & Workflow Generation

### `POST /api/v1/cicd/analyze-files`

**Purpose**: Analyze a list of repository file paths and detect the technology stack (without calling GitHub).

**Method**: POST | **Path**: `/api/v1/cicd/analyze-files`

**Auth**: None (public endpoint).

**Request**:

```json
{
  "files": [
    "package.json",
    "src/App.tsx",
    "package-lock.json",
    "Dockerfile",
    ".github/workflows/ci.yml"
  ]
}
```

**Response** (200 OK):

```json
{
  "language": "javascript",
  "framework": "react",
  "package_manager": "npm",
  "has_docker": true,
  "has_existing_workflows": true,
  "recommended_workflow": "node",
  "project_dir": ".",
  "detected_projects": ["web"],
  "ci_warnings": []
}
```

---

### `POST /api/v1/cicd/generate-workflow`

**Purpose**: Analyze file paths and generate a GitHub Actions workflow YAML.

**Method**: POST | **Path**: `/api/v1/cicd/generate-workflow`

**Auth**: None (public endpoint).

**Request**:

```json
{
  "files": ["requirements.txt", "app/main.py", "tests/test_app.py", "Dockerfile"]
}
```

**Response** (200 OK):

```json
{
  "stack": {
    "language": "python",
    "framework": "fastapi",
    "package_manager": "pip",
    "has_docker": true,
    "has_existing_workflows": false,
    "recommended_workflow": "python",
    "project_dir": ".",
    "detected_projects": [],
    "ci_warnings": []
  },
  "path": ".github/workflows/ai-generated-ci.yml",
  "workflow_yaml": "name: AI Generated CI\non:\n  push:\n    branches:\n      - main\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v3\n      - uses: actions/setup-python@v4\n        with:\n          python-version: '3.11'\n      - run: pip install -r requirements.txt\n      - run: pytest\n"
}
```

---

## 8. Repository Management

### `GET /api/v1/repositories/installed`

**Purpose**: List repositories installed through the GitHub App.

**Method**: GET | **Path**: `/api/v1/repositories/installed`

**Auth**: Required permission `logs:read`.

**Response** (200 OK):

```json
[
  {
    "repository_id": 123456,
    "full_name": "owner/repo-1",
    "installation_id": 789012,
    "status": "active",
    "installed_at": "2026-06-01T08:00:00Z"
  },
  {
    "repository_id": 123457,
    "full_name": "owner/repo-2",
    "installation_id": 789012,
    "status": "active",
    "installed_at": "2026-06-01T08:15:00Z"
  }
]
```

---

### `POST /api/v1/repositories/scan`

**Purpose**: Fetch a GitHub repository tree, analyze files, detect stack, and return CI/CD readiness.

**Method**: POST | **Path**: `/api/v1/repositories/scan`

**Auth**: Required permission `logs:read`.

**Request**:

```json
{
  "repo_full_name": "owner/demo-repo",
  "branch": "main"
}
```

**Response** (200 OK):

```json
{
  "repo_full_name": "owner/demo-repo",
  "files": [
    "package.json",
    "package-lock.json",
    "src/App.tsx",
    ".github/workflows/ci.yml"
  ],
  "stack": {
    "language": "javascript",
    "framework": "react",
    "package_manager": "npm",
    "has_docker": false,
    "has_existing_workflows": true,
    "recommended_workflow": "node",
    "project_dir": ".",
    "detected_projects": [],
    "ci_warnings": []
  },
  "readiness": {
    "score": 82,
    "grade": "B",
    "summary": "Repository is mostly ready for CI/CD.",
    "strengths": [
      "Lockfile found (package-lock.json)",
      "Existing GitHub Actions workflow"
    ],
    "findings": [],
    "recommended_next_actions": [
      "Review generated workflow before merging"
    ]
  }
}
```

**Error** (400 Bad Request):

- Repository not found
- Invalid GitHub token/permissions
- GitHub API error

---

### `POST /api/v1/repositories/create-workflow-pr`

**Purpose**: Save or reuse human approval for a GitHub Actions workflow PR.

**Auth**: Required permission `repositories:write`.

**Request**:

```json
{
  "repo_full_name": "owner/demo-repo",
  "overwrite_existing_workflow": false
}
```

**Response (200 OK)**:

```json
{
  "repo_full_name": "owner/demo-repo",
  "status": "approval_required",
  "approval_required": true,
  "approval_id": "550e8400-e29b-41d4-a716-446655440099",
  "approval_status": "pending",
  "message": "Human approval is required before sending this pull request."
}
```

All workflow PR writes require saved human approval, regardless of `ENABLE_HITL`. Repeated submissions reuse the caller's unexpired pending review for the same repository and replacement option. After expiry, rejection, or failed execution, a new submission creates a fresh review.

### `GET /api/v1/repositories/workflow-pr-status`

**Purpose**: Retrieve the review and execution result after leaving or refreshing the Repositories page.

**Auth**: Required permission `repositories:write`.

**Query**: `repo_full_name` (required), `overwrite_existing_workflow` (default false), `approval_id` (optional UUID).

Without an ID, returns the caller's latest matching review or `null`. With an ID, returns that review only if the caller owns it or is an admin; inaccessible or mismatched IDs return 404.

**Completed response (200 OK)**:

```json
{
  "repo_full_name": "owner/demo-repo",
  "approval_id": "550e8400-e29b-41d4-a716-446655440099",
  "approval_status": "approved",
  "approval_required": false,
  "status": "completed",
  "execution_status": "completed",
  "branch": "ai-cicd/setup-pipeline",
  "workflow_path": ".github/workflows/ai-generated-ci.yml",
  "pull_request_url": "https://github.com/owner/demo-repo/pull/1",
  "message": "Workflow pull request is ready for review."
}
```

Failed results have `status: "failed"` and a sanitized error in `message`. Expired and rejected reviews have `status: "timed_out"` or `"rejected"`. Completed results also include execution ID, expiry time, and detected stack when available. Branch collisions use a timestamp plus random suffix.

### `GET /api/v1/repositories/integration-status`

**Auth**: Required permission `repositories:read`.

Returns `{ "credentials_configured": true }` when a backend PAT or GitHub App credentials are configured. This reports configuration presence, not credential validity or repository authorization. No credential values are returned.

See [Workflow PR troubleshooting](PULL_REQUEST_TROUBLESHOOTING.md) for setup, permissions, and retries.

---

## 9. Failure Prediction

### `POST /api/v1/model/predict-failure`

**Purpose**: Classify CI/CD failure logs with the trained ML model and suggest fixes.

**Method**: POST | **Path**: `/api/v1/model/predict-failure`

**Auth**: Required permission `logs:read`.

**Request**:

```json
{
  "log_text": "Run npm test\nnpm ERR! code ERESOLVE\nnpm ERR! ERESOLVE unable to resolve dependency tree"
}
```

**Response** (200 OK):

```json
{
  "label": "npm_version_conflict",
  "confidence": 0.87,
  "suggested_fix": "Update Node.js version in CI configuration or check package.json compatibility.",
  "recommendation": {
    "summary": "Node.js version incompatibility with npm dependencies",
    "risk_level": "low",
    "requires_approval": false
  }
}
```

**Error** (503 Service Unavailable):

- Model not available (not trained yet)
- ML service failure

**Notes**:
- Confidence ranges from 0.0 to 1.0.
- Common failure labels: `npm_missing_test_script`, `python_import_error`, `docker_build_failure`, etc.

---

## 10. GitHub Webhooks

### `POST /api/v1/webhooks/github`

**Purpose**: Receive GitHub App and workflow events. Triggers failure diagnosis on workflow failure.

**Method**: POST | **Path**: `/api/v1/webhooks/github`

**Auth**: None (HTTP-public), but requires valid `X-Hub-Signature-256` HMAC header.

**Required Headers**:

```
X-Hub-Signature-256: sha256=<hmac-sha256>
X-GitHub-Event: workflow_run
X-GitHub-Delivery: <delivery-uuid>
```

**Supported Events**:

- `installation`: App installed/uninstalled
- `installation_repositories`: Repositories granted/removed
- `workflow_run` (action=completed, conclusion=failure): Failed workflow

**Response** (200 OK):

```json
{
  "received": true,
  "event": "workflow_run"
}
```

**Behavior**:

1. Verifies webhook signature against configured `GITHUB_APP_WEBHOOK_SECRET`.
2. For `workflow_run` events with `conclusion=failure`:
   - Downloads real workflow logs from GitHub.
   - Runs failure prediction model.
   - Stores `WorkflowFailure` record.
   - Logs execution to audit trail.

**Notes**:
- To configure webhooks, see [GitHub E2E Test Guide](GITHUB_E2E_TEST.md#webhook-setup).

---

### `GET /api/v1/webhooks/recent-events`

**Purpose**: List recent webhook events for debugging.

**Method**: GET | **Path**: `/api/v1/webhooks/recent-events`

**Auth**: Required permission `executions:read`.

**Query Parameters**:

- `limit` (int, default=25, max=100): Number of events to return.

**Response** (200 OK):

```json
[
  {
    "id": "exec-uuid-1",
    "tool_name": "github_webhook_handler",
    "action_summary": "Received GitHub workflow_run event for owner/repo",
    "status": "completed",
    "source": "webhook",
    "started_at": "2026-06-01T10:15:00Z",
    "completed_at": "2026-06-01T10:15:05Z",
    "actor": "system",
    "tool_input": "{\"event\": \"workflow_run\", \"conclusion\": \"failure\"}",
    "tool_output": "{\"failure_id\": \"...\", \"prediction\": \"npm_missing_test_script\"}"
  }
]
```

---

## 11. Workflow Failures

### `GET /api/v1/workflow-failures`

**Purpose**: List recent GitHub Actions failure diagnoses.

**Method**: GET | **Path**: `/api/v1/workflow-failures`

**Auth**: Required permission `workflow_failures:read`.

**Query Parameters**:

- `limit` (int, default=50, max=200): Number of failures to return.
- `repo_full_name` (str, optional): Filter by repository.
- `status` (str, optional): Filter by status (e.g., "unresolved", "fix_pr_created").

**Response** (200 OK):

```json
[
  {
    "id": "failure-uuid-1",
    "repo_full_name": "owner/demo-repo",
    "workflow_name": "CI",
    "workflow_run_id": 123456,
    "branch": "main",
    "conclusion": "failure",
    "workflow_run_url": "https://github.com/owner/demo-repo/actions/runs/123456",
    "log_excerpt": "npm ERR! Missing script: test...",
    "predicted_label": "npm_missing_test_script",
    "confidence": 0.82,
    "suggested_fix": "Add test script to package.json",
    "fix_pr_url": null,
    "created_at": "2026-06-01T10:10:00Z"
  }
]
```

---

### `GET /api/v1/workflow-failures/{failure_id}`

**Purpose**: Fetch one workflow failure diagnosis by ID.

**Method**: GET | **Path**: `/api/v1/workflow-failures/{failure_id}`

**Auth**: Required permission `workflow_failures:read`.

**Parameter**:
- `failure_id` (UUID): Workflow failure ID.

**Response** (200 OK):

```json
{
  "id": "failure-uuid-1",
  "repo_full_name": "owner/demo-repo",
  "workflow_name": "CI",
  "workflow_run_id": 123456,
  "branch": "main",
  "conclusion": "failure",
  "workflow_run_url": "https://github.com/owner/demo-repo/actions/runs/123456",
  "log_excerpt": "npm ERR! Missing script: test...",
  "full_log": "...",
  "predicted_label": "npm_missing_test_script",
  "confidence": 0.82,
  "suggested_fix": "Add test script to package.json",
  "recommendation": {
    "summary": "Missing npm test script",
    "risk_level": "low"
  },
  "fix_pr_url": null,
  "created_at": "2026-06-01T10:10:00Z"
}
```

---

### `POST /api/v1/workflow-failures/{failure_id}/create-fix-pr`

**Purpose**: Create an automated fix pull request for a diagnosed failure (requires explicit human approval).

**Method**: POST | **Path**: `/api/v1/workflow-failures/{failure_id}/create-fix-pr`

**Auth**: Required permission `repositories:write`; developers may request only their own failures.

**Parameter**:
- `failure_id` (UUID): Workflow failure ID.

**Request**: (empty body)

**Response - Approval Required (200 OK):**

```json
{
  "workflow_failure_id": "failure-uuid-1",
  "repo_full_name": "owner/demo-repo",
  "status": "approval_required",
  "approval_id": "approval-uuid-1",
  "branch": null,
  "workflow_path": null,
  "pull_request_url": null,
  "message": "Human approval is required before creating this fix PR.",
  "recommendation": {
    "summary": "Add missing npm test script",
    "risk_level": "medium"
  }
}
```

**Execution result after approval (repository changes occur only at this stage):**

```json
{
  "workflow_failure_id": "failure-uuid-1",
  "repo_full_name": "owner/demo-repo",
  "status": "fix_pr_created",
  "branch": "ai-fix/npm-test-script-20260601101530",
  "workflow_path": ".github/workflows/ci.yml",
  "pull_request_url": "https://github.com/owner/demo-repo/pull/2",
  "message": "Fix PR successfully created."
}
```

**Notes**:
- All repository changes require approval, including low-risk fixes and when demo HITL settings are disabled.
- Developers see their own imported records; admins see all records, including webhooks and legacy records.
- Branch format: `ai-cicd/fix-<workflow_run_id>`.
- A repeated fix request reuses its existing unexpired pending approval.

---

### Import and integration endpoints

- `GET /api/v1/workflow-failures/integration-status` reports whether automatic log download and signed webhooks are configured. It exposes no credentials.
- `POST /api/v1/workflow-failures/sync` accepts `{"repo_full_name":"owner/repo","limit":10}` and imports failed or timed-out runs. Public metadata works without a token. Available log-download credentials enable automatic diagnosis. Otherwise the record has `logs_unavailable` and an actionable `diagnosis_error`.
- `POST /api/v1/workflow-failures/import` accepts `repo_full_name`, positive `workflow_run_id`, and `log_text`, with optional `workflow_name` and `branch`. It diagnoses pasted logs and saves the result under the authenticated user. Reimporting the same run updates that user's existing record.

Read [Workflow Failure Guide](WORKFLOW_FAILURES.md) for the UI flow and configuration details.

---

## 12. Approvals (Human-in-the-Loop)

### `GET /api/v1/approvals`

**Purpose**: List approval requests (default: pending only).

**Method**: GET | **Path**: `/api/v1/approvals`

**Auth**: Required permission `approvals:read`.

**Query Parameters**:

- `status_filter` (str, default="pending"): Filter by status (pending, approved, rejected, timed_out).

**Response** (200 OK):

```json
[
  {
    "id": "approval-uuid-1",
    "session_id": "session-uuid",
    "requested_by": "dev@example.com",
    "tool_name": "github_create_workflow_pr",
    "action": "Create GitHub Actions workflow pull request",
    "risk_level": "medium",
    "summary": "Create AI-generated workflow PR for owner/demo-repo",
    "status": "pending",
    "tool_input": "{\"repo_full_name\": \"owner/demo-repo\"}",
    "created_at": "2026-06-01T10:05:00Z",
    "expires_at": "2026-06-01T10:10:00Z",
    "decided_by": null,
    "decision_note": null,
    "decided_at": null
  }
]
```

---

### `GET /api/v1/approvals/{approval_id}`

**Purpose**: Fetch a single approval request by ID.

**Method**: GET | **Path**: `/api/v1/approvals/{approval_id}`

**Auth**: Required permission `approvals:read`.

**Parameter**:
- `approval_id` (UUID): Approval request ID.

**Response** (200 OK):

```json
{
  "id": "approval-uuid-1",
  "session_id": "session-uuid",
  "requested_by": "dev@example.com",
  "tool_name": "github_create_workflow_pr",
  "action": "Create GitHub Actions workflow pull request",
  "risk_level": "medium",
  "summary": "Create AI-generated workflow PR for owner/demo-repo",
  "status": "pending",
  "tool_input": "{\"repo_full_name\": \"owner/demo-repo\"}",
  "created_at": "2026-06-01T10:05:00Z",
  "expires_at": "2026-06-01T10:10:00Z",
  "decided_by": null,
  "decision_note": null,
  "decided_at": null
}
```

---

### `POST /api/v1/approvals/{approval_id}/decide`

**Purpose**: Approve or reject a pending approval request.

**Method**: POST | **Path**: `/api/v1/approvals/{approval_id}/decide`

**Auth**: Required permission `approvals:decide` (admin globally; developers for their own eligible requests).

**Parameter**:
- `approval_id` (UUID): Approval request ID.

**Request**:

```json
{
  "approved": true,
  "note": "Reviewed and approved. Workflow looks good."
}
```

**Response** (200 OK, on approval):

```json
{
  "id": "approval-uuid-1",
  "status": "approved",
  "decided_by": "member@example.com",
  "decided_at": "2026-06-01T10:07:00Z",
  "decision_note": "Reviewed and approved. Workflow looks good.",
  "execution": {
    "id": "exec-uuid-1",
    "tool_name": "github_create_workflow_pr",
    "status": "completed",
    "tool_output": "{\"pull_request_url\": \"https://github.com/owner/demo-repo/pull/1\"}"
  }
}
```

**Response** (200 OK, on rejection):

```json
{
  "id": "approval-uuid-1",
  "status": "rejected",
  "decided_by": "member@example.com",
  "decided_at": "2026-06-01T10:07:00Z",
  "decision_note": "Rejected due to existing workflow.",
  "execution": {
    "id": "exec-uuid-1",
    "tool_name": "github_create_workflow_pr",
    "status": "cancelled"
  }
}
```

**Error** (409 Conflict):

- Approval already decided.

**Error** (410 Gone):

- Approval has expired.

---

## 13. Executions & Audit Logs

### `GET /api/v1/executions`

**Purpose**: List recent agent executions with optional filtering. Also available via `/api/v1/audit`.

**Method**: GET | **Path**: `/api/v1/executions` or `/api/v1/audit`

**Auth**: Required permission `executions:read`.

**Query Parameters**:

- `limit` (int, default=50, max=200): Number of records to return.
- `tool` (str, optional): Filter by tool name (substring match).
- `status` (str, optional): Filter by status (completed, failed, pending).
- `actor` (str, optional): Filter by actor/username.
- `source` (str, optional): Filter by source (api, webhook, agent, system).
- `days` (int, default=7): Look back N days.

**Response** (200 OK):

```json
[
  {
    "id": "exec-uuid-1",
    "tool_name": "failure_prediction_model",
    "action_summary": "Predicted failure for npm test failure",
    "status": "completed",
    "source": "webhook",
    "started_at": "2026-06-01T10:15:00Z",
    "completed_at": "2026-06-01T10:15:02Z",
    "actor": "system",
    "tool_input": "{\"log_length\": 1234}",
    "tool_output": "{\"label\": \"npm_missing_test_script\", \"confidence\": 0.82}",
    "error": null,
    "approval_id": null
  }
]
```

---

### `GET /api/v1/executions/{execution_id}`

**Purpose**: Get details of a specific execution including AI reasoning steps.

**Method**: GET | **Path**: `/api/v1/executions/{execution_id}`

**Auth**: Required permission `executions:read`.

**Parameter**:
- `execution_id` (UUID): Execution record ID.

**Response** (200 OK):

```json
{
  "id": "exec-uuid-1",
  "tool_name": "failure_prediction_model",
  "action_summary": "Predicted failure for npm test failure",
  "status": "completed",
  "source": "webhook",
  "started_at": "2026-06-01T10:15:00Z",
  "completed_at": "2026-06-01T10:15:02Z",
  "actor": "system",
  "tool_input": "{\"log_length\": 1234}",
  "tool_output": "{\"label\": \"npm_missing_test_script\", \"confidence\": 0.82}",
  "error": null,
  "approval_id": null
}
```

---

## 14. Evaluation & Metrics

### `GET /api/v1/evaluation/summary`

**Purpose**: Return model and system evaluation evidence for the demo dashboard.

**Method**: GET | **Path**: `/api/v1/evaluation/summary`

**Auth**: Required permission `metrics:read`.

**Response** (200 OK):

```json
{
  "dataset_size": 500,
  "number_of_labels": 12,
  "accuracy": 0.85,
  "macro_f1": 0.82,
  "weighted_f1": 0.84,
  "total_workflow_failures": 23,
  "total_fix_prs_created": 8,
  "total_audit_logs": 156,
  "total_approvals": 12
}
```

**Notes**:
- Model metrics loaded from `backend/app/ml/reports/metrics.json` (generated during model training).
- Null values indicate metrics are not yet available.
- System metrics aggregated from database records.

---

## 15. Legacy Aliases

The API maintains backward compatibility with legacy URL patterns:

- `/api/agent/*` mirrors `/api/v1/agent/*`
- `/api/v1/audit/*` mirrors `/api/v1/executions/*`
- `/ws/agent` maps directly to the agent WebSocket (`/api/v1/agent/ws/agent`)

Use the `/api/v1/` prefix for all new integrations.

---

## Summary of Documented Endpoints

**Total: 53 Endpoints**

| Category | Count | Status |
| --- | --- | --- |
| Health | 2 | ✓ Implemented |
| Authentication | 8 | ✓ Implemented |
| Multi-Agent Orchestration | 4 | ✓ Implemented |
| CI/CD Analysis | 2 | ✓ Implemented |
| Repository Management | 3 | ✓ Implemented |
| Failure Prediction | 1 | ✓ Implemented |
| GitHub Webhooks | 2 | ✓ Implemented |
| Workflow Failures | 3 | ✓ Implemented |
| Approvals (HITL) | 3 | ✓ Implemented |
| Executions/Audit | 2 | ✓ Implemented |
| Evaluation & Metrics | 1 | ✓ Implemented |
| **Total** | **53** | |

---

## OpenAPI / Swagger

Interactive API documentation generated from FastAPI's OpenAPI schema:

- **Swagger UI**: `GET /docs`
- **ReDoc UI**: `GET /redoc`
- **OpenAPI JSON**: `GET /openapi.json`
