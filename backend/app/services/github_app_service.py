"""GitHub App authentication, webhook verification, and installation storage."""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any

import requests  # type: ignore[import-untyped]
from jose import jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import RepositoryInstallation

GITHUB_API_BASE_URL = "https://api.github.com"
REQUEST_TIMEOUT_SECONDS = 30


class GitHubAppError(RuntimeError):
    """Raised when GitHub App authentication or installation access fails."""


def _private_key() -> str:
    key = settings.GITHUB_APP_PRIVATE_KEY.strip()
    if not key:
        raise GitHubAppError("GITHUB_APP_PRIVATE_KEY is not configured.")
    return key.replace("\\n", "\n")


def create_app_jwt() -> str:
    """Create a short-lived GitHub App JWT signed with the app private key."""
    if not settings.GITHUB_APP_ID:
        raise GitHubAppError("GITHUB_APP_ID is not configured.")

    now = datetime.now(tz=timezone.utc)
    payload = {
        "iat": int((now - timedelta(seconds=60)).timestamp()),
        "exp": int((now + timedelta(minutes=9)).timestamp()),
        "iss": str(settings.GITHUB_APP_ID),
    }
    return jwt.encode(payload, _private_key(), algorithm="RS256")


def _github_headers(token: str, *, accept: str = "application/vnd.github+json") -> dict[str, str]:
    return {
        "Accept": accept,
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "smart-devops-assistant-github-app",
    }


def _response_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200] or response.reason
    if isinstance(payload, dict):
        return str(payload.get("message") or response.reason)
    return response.reason


def _raise_for_response(response: requests.Response, context: str) -> None:
    if response.status_code < 400:
        return

    message = _response_message(response)
    if response.status_code == 401:
        raise GitHubAppError(f"{context}: invalid GitHub App credentials.")
    if response.status_code == 403:
        if response.headers.get("X-RateLimit-Remaining") == "0" or "rate limit" in message.lower():
            raise GitHubAppError(f"{context}: GitHub API rate limit exceeded.")
        raise GitHubAppError(f"{context}: insufficient GitHub App permissions.")
    if response.status_code == 404:
        raise GitHubAppError(f"{context}: installation or repository not found.")
    raise GitHubAppError(f"{context}: GitHub API error ({response.status_code}) {message}")


def get_installation_access_token(installation_id: int | str) -> str:
    """Exchange the GitHub App JWT for an installation access token."""
    if not installation_id:
        raise GitHubAppError("GitHub App installation id is required.")

    url = f"{GITHUB_API_BASE_URL}/app/installations/{int(installation_id)}/access_tokens"
    try:
        response = requests.post(
            url,
            headers=_github_headers(create_app_jwt()),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise GitHubAppError("Unable to create installation access token: request failed.") from exc

    _raise_for_response(response, "Unable to create installation access token")
    payload = response.json()
    token = payload.get("token") if isinstance(payload, dict) else None
    if not token:
        raise GitHubAppError("Unable to create installation access token: response did not include a token.")
    return str(token)


def verify_webhook_signature(payload: bytes, signature: str | None) -> bool:
    """
    Verify the GitHub webhook HMAC-SHA256 signature.

    GitHub App secret is preferred. The legacy repository webhook secret remains
    as a fallback so local PAT-based testing keeps working.
    """
    secret = settings.GITHUB_APP_WEBHOOK_SECRET or settings.GITHUB_WEBHOOK_SECRET
    if not secret:
        return True
    if not signature:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def get_installation_repositories(installation_id: int | str) -> list[dict[str, Any]]:
    """Return repositories currently available to a GitHub App installation."""
    token = get_installation_access_token(installation_id)
    repositories: list[dict[str, Any]] = []
    page = 1

    while True:
        try:
            response = requests.get(
                f"{GITHUB_API_BASE_URL}/installation/repositories",
                headers=_github_headers(token),
                params={"per_page": 100, "page": page},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise GitHubAppError("Unable to list installation repositories: request failed.") from exc

        _raise_for_response(response, "Unable to list installation repositories")
        payload = response.json()
        batch = payload.get("repositories", []) if isinstance(payload, dict) else []
        repositories.extend(repo for repo in batch if isinstance(repo, dict))
        if len(batch) < 100:
            break
        page += 1

    return repositories


def repository_values(repository: dict[str, Any], installation_id: int | str, status: str = "active") -> dict[str, Any]:
    """Normalize a GitHub repository payload for RepositoryInstallation."""
    full_name = str(repository.get("full_name") or "").strip()
    if not full_name or "/" not in full_name:
        raise GitHubAppError("Repository payload does not include full_name.")
    owner, repo = full_name.split("/", 1)
    return {
        "installation_id": int(installation_id),
        "repo_full_name": full_name,
        "owner": owner,
        "repo": repo,
        "default_branch": str(repository.get("default_branch") or "main"),
        "status": status,
    }


async def upsert_repository_installation(
    db: AsyncSession,
    *,
    installation_id: int | str,
    repository: dict[str, Any],
    status: str = "active",
) -> RepositoryInstallation:
    """Create or update one installed repository row."""
    values = repository_values(repository, installation_id, status)
    result = await db.execute(
        select(RepositoryInstallation).where(
            RepositoryInstallation.repo_full_name == values["repo_full_name"]
        )
    )
    record = result.scalar_one_or_none()
    now = datetime.now(tz=timezone.utc)

    if record is None:
        record = RepositoryInstallation(**values)
        db.add(record)
    else:
        record.installation_id = values["installation_id"]
        record.owner = values["owner"]
        record.repo = values["repo"]
        record.default_branch = values["default_branch"]
        record.status = values["status"]
        record.updated_at = now

    await db.flush()
    await db.refresh(record)
    return record


async def mark_repository_removed(
    db: AsyncSession,
    *,
    installation_id: int | str,
    repository: dict[str, Any],
) -> RepositoryInstallation:
    """Mark a repository installation as removed/deleted."""
    return await upsert_repository_installation(
        db,
        installation_id=installation_id,
        repository=repository,
        status="removed",
    )


async def list_installed_repositories(
    db: AsyncSession,
    *,
    status: str | None = "active",
) -> list[RepositoryInstallation]:
    """List GitHub App repository installations tracked locally."""
    stmt = select(RepositoryInstallation).order_by(RepositoryInstallation.repo_full_name.asc())
    if status:
        stmt = stmt.where(RepositoryInstallation.status == status)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_installation_for_repo(db: AsyncSession, repo_full_name: str) -> RepositoryInstallation | None:
    """Return the active installation row for a repository, if present."""
    result = await db.execute(
        select(RepositoryInstallation).where(
            func.lower(RepositoryInstallation.repo_full_name) == repo_full_name.lower(),
            RepositoryInstallation.status == "active",
        ).order_by(RepositoryInstallation.created_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()
