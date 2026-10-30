"""Health check endpoints."""
from pathlib import Path

import docker
from docker.errors import DockerException
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


def _model_path() -> Path:
    default_model_path = Path(__file__).resolve().parents[2] / "ml" / "failure_model.joblib"
    return Path(settings.FAILURE_MODEL_PATH) if settings.FAILURE_MODEL_PATH else default_model_path


def _status_flags() -> dict:
    model_path = _model_path()
    github_configured = bool(
        settings.GITHUB_TOKEN
        or (settings.GITHUB_APP_ID and settings.GITHUB_APP_PRIVATE_KEY)
    )
    return {
        "status": "ok",
        "desktop_mode": settings.DESKTOP_MODE,
        "auth_disabled": settings.auth_disabled,
        "mobile_supported": True,
        "model_available": model_path.exists(),
        "github_configured": github_configured,
    }


@router.get("/health", tags=["Health"])
async def health_check():
    return {"service": "Smart DevOps Assistant", **_status_flags()}


@router.get("/health/status", tags=["Health"])
async def system_status():
    """Return safe local status flags for desktop and demo dashboards."""
    flags = _status_flags()
    model_path = _model_path()
    docker_available = False
    docker_message = "Docker Desktop is not reachable."
    try:
        client = docker.from_env(timeout=2)
        client.ping()
        docker_available = True
        docker_message = "Docker Desktop is running."
    except DockerException:
        docker_available = False

    return {
        "backend_api": {"status": "ok", "message": "Backend API is reachable."},
        "desktop_mode": {
            "enabled": settings.DESKTOP_MODE,
            "auth_disabled": settings.auth_disabled,
        },
        "mobile_supported": flags["mobile_supported"],
        "docker": {"available": docker_available, "message": docker_message},
        "github": {
            "configured": flags["github_configured"],
            "message": "GitHub credentials are configured."
            if flags["github_configured"]
            else "GitHub token or GitHub App credentials are not configured.",
        },
        "ml_model": {
            "available": flags["model_available"],
            "path": model_path.name,
            "message": "Failure classifier model artifact is available."
            if model_path.exists()
            else "Failure classifier model artifact is missing.",
        },
    }


@router.get("/", tags=["Health"])
async def root():
    return {
        "name": "Agentic AI-Powered Smart DevOps Assistant",
        "version": "1.0.0",
        "docs": "/docs",
    }
