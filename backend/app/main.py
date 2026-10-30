"""
Smart DevOps Assistant — FastAPI Application Entry Point
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    agent,
    approvals,
    auth,
    cicd,
    executions,
    evaluation,
    health,
    model,
    repositories,
    webhooks,
    workflow_failures,
)
from app.core.config import settings
from app.core.database import init_db
from app.core.logging import setup_logging
from app.core.security_headers import SecurityHeadersMiddleware

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup / shutdown lifecycle."""
    await init_db()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Agentic AI-Powered Smart DevOps Assistant — "
        "autonomous infrastructure management through natural language."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── Middleware ────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(health.router,      tags=["Health"])
app.include_router(health.router,      prefix="/api/v1", tags=["Health"])
app.include_router(auth.router,        prefix="/api/v1/auth",       tags=["Authentication"])
app.include_router(agent.router,       prefix="/api/v1/agent",      tags=["Agent"])
# Legacy API and WebSocket URLs kept for existing clients/tests.
app.include_router(agent.router,       prefix="/api/agent",         tags=["Agent"])
app.include_router(agent.router,       prefix="/ws",                tags=["Agent WebSocket"])
app.add_api_websocket_route("/ws/agent", agent.agent_ws)
app.include_router(approvals.router,   prefix="/api/v1/approvals",  tags=["HITL Approvals"])
app.include_router(executions.router,  prefix="/api/v1/executions", tags=["Executions"])
app.include_router(executions.router,  prefix="/api/v1/audit",      tags=["Audit"])
app.include_router(evaluation.router,  prefix="/api/v1/evaluation", tags=["Evaluation"])
app.include_router(model.router,       prefix="/api/v1/model",      tags=["Failure Prediction Model"])
app.include_router(cicd.router,        prefix="/api/v1/cicd",       tags=["CI/CD"])
app.include_router(repositories.router, prefix="/api/v1/repositories", tags=["Repositories"])
app.include_router(webhooks.router,    prefix="/api/v1/webhooks",   tags=["Webhooks"])
app.include_router(
    workflow_failures.router,
    prefix="/api/v1/workflow-failures",
    tags=["Workflow Failures"],
)
