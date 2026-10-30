"""QA-only application: real routes/database, deterministic external boundaries.

Started only by qa.run in an empty temporary directory. Never import in production.
"""
import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


workspace = Path(os.environ["QA_TEMP_DIR"]).resolve()
if not (workspace / ".isolated-qa").is_file():
    raise RuntimeError("QA server requires a disposable directory created by qa.run.")
if os.environ.get("DATABASE_URL") != f"sqlite+aiosqlite:///{workspace / 'qa.db'}":
    raise RuntimeError("QA server refuses a non-disposable database.")

from app.main import app  # noqa: E402
from app.api.routes import agent, repositories, health  # noqa: E402
from app.core.database import Base, engine, AsyncSessionLocal  # noqa: E402
from app.core.security import UserRole, hash_password  # noqa: E402
from app.models.models import ApprovalRequest, Execution, User, WorkflowFailure  # noqa: E402
from app.tools import github_tool, docker_tool, shell_tool  # noqa: E402


def fixture_id(number):
    return str(UUID(int=number))


def forbidden(*args, **kwargs):
    raise RuntimeError("External operations are disabled in isolated QA.")


def repository_inputs(repo, *args, **kwargs):
    repo = github_tool._validate_repo_full_name(repo)
    if repo == "qa/auth-error":
        raise github_tool.GitHubToolError("GitHub authentication failed for the isolated fixture.")
    if repo not in {"qa/demo", "qa/workflow-demo"}:
        raise github_tool.GitHubToolError("Repository is outside the isolated QA fixture allowlist.")
    files = ["package.json", "src/App.tsx", "tests/app.test.ts", ".env.example"]
    return {"files": files, "analysis_inputs": files}


class FixtureAgent:
    async def _response(self, message):
        if "[qa:delay]" in message:
            await asyncio.sleep(1.2)
        if "[qa:error]" in message:
            raise RuntimeError("Controlled QA agent failure")
        return "QA deterministic response: review the workflow and its test command."

    async def chat(self, message, db):
        return {"output": await self._response(message), "intermediate_steps": []}

    async def stream_chat(self, message, db):
        yield await self._response(message)


def get_fixture_agent(*args, **kwargs):
    return FixtureAgent()


@asynccontextmanager
async def lifespan(application):
    # Create every table explicitly: unlike demo startup, setup errors are fatal.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        for number, name, role in [(100, "qa-member", UserRole.DEVELOPER),
                                   (101, "qa-admin", UserRole.ADMIN),
                                   (102, "qa-other", UserRole.DEVELOPER)]:
            db.add(User(id=fixture_id(number), username=name, email=f"{name}@example.com", role=role,
                        hashed_password=hash_password(os.environ["QA_TEST_PASSWORD"]), is_active=True))
        for number, summary, expiry, tool in [
            (1, "QA pending review", now + timedelta(hours=1), "github_create_workflow_pr"),
            (2, "QA expired review", now - timedelta(minutes=1), "github_create_workflow_pr"),
            (3, "QA privileged review", now + timedelta(hours=1), "admin_set_user_active"),
            (4, "QA review expiring soon", now + timedelta(seconds=30), "github_create_workflow_pr"),
        ]:
            db.add(ApprovalRequest(id=fixture_id(number), requested_by="qa-member", tool_name=tool,
                                   action=summary, summary=summary, risk_level="high", status="pending",
                                   tool_input=json.dumps({"repo_full_name": "qa/demo"}),
                                   created_at=now, expires_at=expiry))
        for number, actor, status in [(10, "qa-member", "completed"), (11, "qa-member", "failed"),
                                      (12, "qa-other", "completed")]:
            db.add(Execution(id=fixture_id(number), requested_by=actor, tool_name="qa_fixture",
                             summary=f"QA {actor} {status} audit record", status=status,
                             details=json.dumps({"fixture": True}), source="qa", started_at=now,
                             completed_at=now))
        db.add(WorkflowFailure(id=fixture_id(20), repo_full_name="qa/demo", workflow_run_id=1234,
                               requested_by="qa-member", workflow_name="QA CI", branch="qa-fixture",
                               conclusion="failure", log_excerpt='npm ERR! Missing script: "test"',
                               predicted_label="npm_missing_test_script", confidence=0.82,
                               suggested_fix="Add a test script in package.json.", status="diagnosed",
                               created_at=now))
        await db.commit()
    agent.get_or_create_agent = get_fixture_agent
    repositories.get_repository_analysis_inputs = repository_inputs
    github_tool.get_repository_analysis_inputs = repository_inputs
    github_tool._get_client = forbidden
    github_tool.create_workflow_pr = forbidden
    github_tool.create_fix_pr = forbidden
    github_tool.trigger_workflow = forbidden
    docker_tool.list_containers = lambda: "QA fixture: no running containers."
    docker_tool.get_container_logs = lambda *args: "QA fixture container log."
    shell_tool.execute_safe_shell_command = forbidden
    # Prevent health checks from accessing the host Docker socket.

    def no_docker(*args, **kwargs):
        raise health.DockerException("QA Docker boundary")
    health.docker.from_env = no_docker
    yield
    await engine.dispose()


app.router.lifespan_context = lifespan
faults = {}
FAULT_PATHS = {"/api/v1/audit", "/api/v1/health/status", "/api/v1/workflow-failures",
               "/api/v1/evaluation/summary", "/api/v1/approvals", "/api/v1/repositories/scan",
               "/api/v1/agent/chat"}


class FixtureSocketGate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket" and faults.get("/api/v1/agent/chat") == "error":
            await send({"type": "websocket.close", "code": 1013})
            return
        await self.app(scope, receive, send)


app.add_middleware(FixtureSocketGate)


@app.middleware("http")
async def controlled_faults(request: Request, call_next):
    fault = faults.get(request.url.path.rstrip("/"))
    if fault == "error":
        return JSONResponse({"detail": "Controlled QA backend failure. Please retry."}, status_code=503)
    if fault == "empty":
        return JSONResponse([])
    return await call_next(request)


@app.post("/__qa/control")
async def control(request: Request):
    if request.headers.get("X-QA-Control") != os.environ["QA_CONTROL_TOKEN"]:
        raise HTTPException(403, "QA control denied")
    payload = await request.json()
    if not isinstance(payload, dict) or any(path not in FAULT_PATHS or mode not in {"error", "empty"}
                                            for path, mode in payload.items()):
        raise HTTPException(400, "Unsupported QA fault")
    faults.clear()
    faults.update(payload)
    return {"isolated_qa": True}


@app.get("/__qa/ready")
def ready():
    return {"isolated_qa": True, "run_id": os.environ["QA_RUN_ID"]}


@app.post("/__qa/expiry")
async def fixture_expiry(request: Request):
    if request.headers.get("X-QA-Control") != os.environ["QA_CONTROL_TOKEN"]:
        raise HTTPException(403, "QA control denied")
    async with AsyncSessionLocal() as db:
        record = await db.get(ApprovalRequest, fixture_id(4))
        record.expires_at = datetime.now(timezone.utc) + timedelta(seconds=5)
        await db.commit()
    return {"isolated_qa": True}


# Serve the real built React bundle on the same origin as the real API.
dist = Path(os.environ["QA_FRONTEND_DIST"])
app.mount("/assets", StaticFiles(directory=dist / "assets"), name="qa-assets")
app.router.routes = [route for route in app.router.routes if getattr(route, "path", None) != "/"]


@app.get("/{path:path}")
def frontend(path: str):
    if path.startswith(("api/", "__qa/")):
        raise HTTPException(404, "Not found")
    candidate = (dist / path).resolve()
    if candidate.is_relative_to(dist) and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(dist / "index.html")
