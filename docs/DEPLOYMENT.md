# Deployment Guide

This guide explains deployment architecture and environment requirements. It is not a production hardening checklist, but it documents how the project is intended to run for local demos and controlled deployments.

## 1. Deployment Modes

The project supports four practical modes:

| Mode | Use case | Database |
| --- | --- | --- |
| Local lightweight | Fast demo and development | SQLite |
| Local full stack | Demo with containers, Redis, worker, database | PostgreSQL through Docker Compose |
| Hosted backend/frontend | More realistic deployment | PostgreSQL or Supabase-compatible database |
| Windows desktop | Local single-user app with no login screen | SQLite or configured backend DB |

The core CI/CD features do not require Docker. Docker Compose is only a convenient way to run the full app stack together.

Web mode keeps login, JWT cookies, RBAC, approvals, and audit logging. Desktop mode sets `DESKTOP_MODE=true` and `DISABLE_AUTH=true`, opens as `Desktop User`, hides Users & Roles and Sign out, bypasses JWT/RBAC for local use, and keeps audit records under `desktop_user`.

The repository deployment workflow uses SSH to the existing EC2 Compose deployment after a successful `CI Pipeline` push run on `main`. It requires three EC2 repository secrets and a public SSH host identity variable; missing settings fail deployment while CI remains a separate workflow. See [EC2 setup, validation, troubleshooting, and rollback](EC2_DEPLOYMENT.md). AWS credentials and ECR are not required.

## 2. Runtime Components

```mermaid
flowchart TB
    Browser[Browser] --> Frontend[React Frontend]
    Frontend --> Backend[FastAPI Backend]
    Backend --> DB[(Database)]
    Backend --> Redis[(Redis)]
    Redis --> Worker[Celery Worker]
    Redis --> Flower[Flower Monitoring UI]
    Backend --> GitHub[GitHub API]
    GitHub --> Webhook[Webhook Callback]
    Webhook --> Backend
```

Required for the main MVP:

- backend,
- frontend,
- database,
- GitHub token or GitHub App credentials for real repository actions,
- trained model artifacts.

Optional:

- Redis,
- Celery worker,
- Flower,
- Docker socket for local container inspection.

## 3. Important Environment Variables

Backend:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy database URL. |
| `SECRET_KEY` | JWT signing secret. Must be strong outside local demo. |
| `ALLOWED_ORIGINS` | Comma-separated or JSON list of frontend origins. |
| `COOKIE_SECURE` | Explicitly controls the cookie's Secure flag in every environment. Use true behind HTTPS. |
| `COOKIE_SAMESITE` | `lax`, `strict`, or `none`. |
| `DESKTOP_MODE` | Enables local desktop behavior when true. Defaults to false. |
| `DISABLE_AUTH` | Bypasses JWT/RBAC when true. Defaults to false. |
| `REDIS_URL` | Redis URL for memory/task support. |
| `CELERY_BROKER_URL` | Celery broker URL. Falls back to Redis URL if configured by compose. |
| `CELERY_RESULT_BACKEND` | Celery result backend. |
| `GITHUB_TOKEN` | PAT fallback for local testing. |
| `GITHUB_APP_ID` | GitHub App ID for installation tokens. |
| `GITHUB_APP_PRIVATE_KEY` | GitHub App private key. |
| `GITHUB_APP_WEBHOOK_SECRET` | Secret used to verify GitHub App webhooks. |
| `GITHUB_WEBHOOK_SECRET` | Legacy/shared webhook secret fallback. |
| `FAILURE_MODEL_PATH` | Optional override for model artifact path. |
| `FIX_MAPPING_PATH` | Optional override for fix mapping path. |
| `ENABLE_HITL` | Enables human approval gates. |

Frontend:

| Variable | Purpose |
| --- | --- |
| `VITE_API_BASE_URL` | Backend base URL. |
| `VITE_DESKTOP_MODE` | Opens the frontend without login and displays Desktop User when true. |
| `VITE_MOBILE_MODE` | Enables mobile packaging behavior for Capacitor builds. |
| `VITE_DISABLE_AUTH` | Frontend-side auth bypass flag for local packaged demos only. |

The current EC2 demo at `http://3.27.37.180/` uses `ENVIRONMENT=production`,
`COOKIE_SECURE=false`, and `COOKIE_SAMESITE=lax`. The explicit `COOKIE_SECURE`
setting controls login, refresh, and logout cookies; `ENVIRONMENT` does not
override it. This allows the browser to send its HttpOnly authentication cookie
to `/api/v1/auth/me` and the agent WebSocket over the demo's HTTP connection.
Authentication, RBAC, JWT validation, HttpOnly, and SameSite remain enabled.
When HTTPS is added, change `COOKIE_SECURE` back to `true` in the deployed backend
environment and restart/recreate the backend so the new setting takes effect.

Desktop production frontend env:

```bash
VITE_DESKTOP_MODE=true
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Backend desktop env:

```bash
DESKTOP_MODE=true
DISABLE_AUTH=true
```

Mobile builds should set `VITE_API_BASE_URL` to a backend URL the device can reach, such as a LAN IP or public HTTPS tunnel. The backend does not run inside the Android app.

## 4. GitHub App Requirements

For production-style repository access, use a GitHub App installation.

Recommended repository permissions:

- Metadata: read-only.
- Contents: read and write.
- Pull requests: read and write.
- Actions: read and write if workflow run actions are needed.
- Workflows: read and write for workflow file updates.

Recommended events:

- `workflow_run`
- `installation`
- `installation_repositories`

Webhook URL shape:

```text
https://your-backend-domain/api/v1/webhooks/github
```

Localhost is not publicly reachable by GitHub. For local webhook testing, expose the backend through a secure tunnel and use that public URL.

Use [GitHub End-to-End Checklist](GITHUB_E2E_CHECKLIST.md) to verify the full repository scan, approval, pull request, webhook, and diagnosis loop.

## 4.1 Windows Desktop Build

Recommended easy setup from PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\desktop\setup-windows.ps1
```

This installs backend, frontend, and Electron dependencies, builds the desktop frontend, packages the backend executable, and creates a Windows installer in `desktop\dist`.

Run from source after setup:

```powershell
.\desktop\run-desktop.ps1
```

Manual developer build:

```bash
make setup
make build-frontend
make build-backend-exe
make desktop-check
make desktop-build-win
```

Run the local development shell with:

```bash
make desktop-dev
```

Docker tools require Docker Desktop running on the same machine. GitHub token values must stay in backend environment variables and should never be stored in frontend `.env` files.

## 5. Database Notes

The app can auto-create tables through startup initialization for local/demo use.

Main tables:

- `users`
- `user_sessions`
- `chat_messages`
- `approval_requests`
- `executions`
- `workflow_failures`
- `repository_installations`
- `automation_rules`

For a production-like deployment, use proper database migrations and backups.

## 6. Security Checklist

Before any public deployment:

- Replace default admin credentials.
- Use a strong `SECRET_KEY`.
- Enable HTTPS.
- Set `COOKIE_SECURE=true`.
- Restrict `ALLOWED_ORIGINS`.
- Use GitHub App installation tokens instead of broad PATs.
- Store secrets in the deployment secret manager.
- Keep `ENABLE_HITL=true`.
- Do not mount Docker socket unless local infrastructure inspection is required.
- Review logs to confirm secrets are redacted.

## 7. Model Artifacts

The backend expects model artifacts under `backend/app/ml/` unless environment variables override them.

Required runtime artifacts:

- `failure_model.joblib`
- `fix_mapping.joblib`

If the artifacts are unavailable, prediction endpoints return service-unavailable style errors instead of silently guessing.

## 8. GitHub Releases and service health

`.github/workflows/release.yml` publishes releases when a `vMAJOR.MINOR.PATCH`
tag is pushed. It rejects malformed versions and leading zeros, checks the tagged
commit against fetched main history, and generates release notes with GitHub's
built-in token. Existing tags and releases are never overwritten. The workflow
does not upload application archives or environment files and requires no PAT.

Create release tags only for a revision that has passed CI, completed deployment,
and passed the public frontend/proxied API checks. The release workflow validates
tag format and main ancestry; the operator verifies deployment before tagging.

`.github/workflows/packages.yml` publishes the backend and frontend Docker images
to GitHub Packages (GHCR) on the same version tags. It verifies main ancestry and
requires successful main CI for the exact tagged commit before publishing. The
images are built with the existing Dockerfiles, including Python/npm dependencies;
the backend image also supports the Celery worker and Flower commands. Environment
files stay excluded by the existing Docker ignore rules.

Image names are the lowercase repository path with `-backend` or `-frontend`:

```text
ghcr.io/malithi2001/autonomous-infrastructure-provisioning-and-delivery-via-agentic-ai-backend:v1.0.0
ghcr.io/malithi2001/autonomous-infrastructure-provisioning-and-delivery-via-agentic-ai-frontend:v1.0.0
```

Each new image also receives a `sha-<full-commit-sha>` tag and OCI source, revision,
and version labels. Existing version images are preserved when a job is rerun.
Registry authentication uses the built-in `GITHUB_TOKEN` with `packages: write`;
no additional PAT or registry password secret is needed. New GHCR packages default
to private visibility; authenticated users with package access can pull them. A
package owner can change visibility in GitHub's package settings if public pulls
are desired. EC2 continues using its current CI-gated build/deployment workflow.

To publish an existing release without moving its Git tag or changing its release:

```bash
gh workflow run packages.yml --ref main -f release_tag=v1.0.0
```

Compose health checks match each service: backend HTTP health, PostgreSQL
readiness, Redis ping, the Celery worker's own node ping, Flower's internal
`/flower/healthcheck`, and the frontend's HTTP root. Worker and Flower override the
backend image's inherited HTTP probe, which would otherwise report them as
unhealthy even when their actual services work.

## 9. Scaling Notes

For a stronger deployment:

- run multiple backend workers behind a reverse proxy,
- use PostgreSQL instead of SQLite,
- use Redis-backed memory,
- move long-running GitHub log downloads to Celery,
- use object storage for larger log artifacts,
- monitor error rates and webhook delivery failures,
- add database migrations for schema changes.
