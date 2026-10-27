"""
GitHub Tool — LangChain tool functions for GitHub Actions CI/CD integration.
Uses PyGithub SDK. Requires GITHUB_TOKEN in environment.
"""
from __future__ import annotations

import base64
import io
import re
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Any, Mapping

import requests  # type: ignore[import-untyped]
from github import Github, GithubException

from app.core.config import settings
from app.core.logging import logger
from app.services.repo_analyzer import detect_stack
from app.services.workflow_generator import WORKFLOW_PATH
from app.services.workflow_generator import generate_workflow

_gh_client: Github | None = None
WORKFLOW_BRANCH = "ai-cicd/setup-pipeline"
GITHUB_API_BASE_URL = "https://api.github.com"
WORKFLOW_LOG_TEXT_LIMIT = 200_000
WORKFLOW_LOG_FILE_LIMIT = 80
REQUEST_TIMEOUT_SECONDS = 30
ANALYSIS_SNAPSHOT_TEXT_LIMIT = 12_000
ANALYSIS_SNAPSHOT_FILE_LIMIT = 40
_ANALYSIS_MANIFEST_NAMES = {
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "pipfile",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
}
_ANALYSIS_SOURCE_NAMES = {"main.py", "app.py", "server.py"}

_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_TOKEN_PATTERNS = [
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"(?i)\b(bearer|token)\s+[A-Za-z0-9._~+/=-]{20,}"),
    re.compile(r"(?i)\b(x-access-token:)\s*[A-Za-z0-9._~+/=-]{20,}"),
    re.compile(r"(?i)\b(secret|api[_-]?key|access[_-]?token)=['\"]?[A-Za-z0-9._~+/=-]{16,}['\"]?"),
    re.compile(
        r"(?i)\b(password|passwd|secret|api[_-]?key|database_url|redis_url|refresh[_-]?token|jwt|client[_-]?secret)"
        r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,]+)"
    ),
]


class GitHubToolError(RuntimeError):
    """Raised when a GitHub write operation cannot be completed safely."""

    pass


def _get_client(token: str | None = None) -> Github:
    global _gh_client
    if token:
        return Github(token)
    if _gh_client is None:
        if not settings.GITHUB_TOKEN:
            raise GitHubToolError(
                "GITHUB_TOKEN is not configured. "
                "Set it in backend/.env to enable GitHub integration."
            )
        _gh_client = Github(settings.GITHUB_TOKEN)
    return _gh_client


def _default_repo() -> str:
    repo = settings.GITHUB_REPO_FULL_NAME.strip()
    if not repo:
        raise RuntimeError(
            "No repository specified. Pass `owner/repo` or set "
            "GITHUB_REPO_FULL_NAME in backend/.env."
        )
    return repo


def _repo_full_name(owner: str, repo: str) -> str:
    owner = owner.strip()
    repo = repo.strip()
    if not owner or not repo:
        raise GitHubToolError("Both owner and repo are required.")
    return f"{owner}/{repo}"


def _get_repo(owner: str, repo: str, token: str | None = None):
    try:
        return _get_client(token).get_repo(_repo_full_name(owner, repo))
    except GithubException as exc:
        raise GitHubToolError(_github_error_message(exc, "Unable to access repository")) from exc


def _get_repo_by_full_name(repo_full_name: str, token: str | None = None):
    repo_full_name = _validate_repo_full_name(repo_full_name)
    try:
        return _get_client(token).get_repo(repo_full_name)
    except GithubException as exc:
        raise GitHubToolError(_github_error_message(exc, "Unable to access repository")) from exc


def _github_error_message(exc: GithubException, context: str) -> str:
    message = exc.data.get("message", str(exc)) if isinstance(exc.data, dict) else str(exc)
    status = getattr(exc, "status", None)
    if status == 401 or "bad credentials" in message.lower():
        return f"{context}: invalid GitHub token."
    if status == 403:
        if "rate limit" in message.lower():
            return f"{context}: GitHub API rate limit exceeded."
        return f"{context}: insufficient GitHub permissions for this operation."
    if status == 404:
        return f"{context}: repository or resource not found."
    return f"{context}: GitHub API error ({status}) {message}"


def _validate_repo_full_name(repo_full_name: str) -> str:
    """Validate and normalize an owner/repo name."""
    normalized = repo_full_name.strip()
    if not normalized or "/" not in normalized:
        raise GitHubToolError("Repository full name is required in the form 'owner/repo'.")
    owner, repo = normalized.split("/", 1)
    if (
        len(normalized) > 255 or not re.fullmatch(r"[A-Za-z0-9_.-]+", owner.strip())
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", repo.strip())
        or repo.strip() in {".", ".."} or owner.strip() in {".", ".."}
    ):
        raise GitHubToolError("Repository full name is required in the form 'owner/repo'.")
    return f"{owner.strip()}/{repo.strip()}"


def _github_rest_headers(token: str | None = None) -> dict[str, str]:
    """Return headers for GitHub REST API requests."""
    auth_token = token or settings.GITHUB_TOKEN
    if not auth_token:
        raise GitHubToolError(
            "GitHub token is not configured. Set GITHUB_TOKEN for local development "
            "or install the GitHub App for repository access."
        )
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {auth_token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "smart-devops-assistant",
    }


def _response_message(response: requests.Response) -> str:
    """Extract a safe GitHub error message from a response."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200] or response.reason
    if isinstance(payload, dict):
        return str(payload.get("message") or response.reason)
    return response.reason


def _raise_for_log_response(response: requests.Response, repo_full_name: str, run_id: int) -> None:
    """Convert GitHub REST failures into clear tool errors."""
    if response.status_code < 400:
        return

    message = _response_message(response)
    lowered = message.lower()
    context = f"Unable to download workflow logs for {repo_full_name} run {run_id}"

    if response.status_code == 401 or "bad credentials" in lowered:
        raise GitHubToolError(f"{context}: invalid GitHub token.")
    if response.status_code == 403:
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining == "0" or "rate limit" in lowered:
            reset = response.headers.get("X-RateLimit-Reset")
            suffix = f" Retry after reset timestamp {reset}." if reset else ""
            raise GitHubToolError(f"{context}: GitHub API rate limit exceeded.{suffix}")
        raise GitHubToolError(f"{context}: insufficient GitHub permissions to read Actions logs.")
    if response.status_code == 404:
        raise GitHubToolError(f"{context}: repository, workflow run, or logs were not found.")
    if response.status_code == 410:
        raise GitHubToolError(f"{context}: logs are no longer available.")

    raise GitHubToolError(f"{context}: GitHub API error ({response.status_code}) {message}")


def _clean_log_text(value: str) -> str:
    """Remove terminal color codes and redact token-looking values."""
    cleaned = _ANSI_ESCAPE_RE.sub("", value)
    for pattern in _TOKEN_PATTERNS:
        cleaned = pattern.sub(lambda match: f"{match.group(1)} [REDACTED]" if match.groups() else "[REDACTED]", cleaned)
    return cleaned.replace("\x00", "")


def clean_workflow_log(value: str) -> str:
    """Apply the same redaction to pasted logs as downloaded GitHub logs."""
    return _clean_log_text(value)


def list_failed_workflow_runs(repo_full_name: str, limit: int = 10, *, token: str | None = None) -> list[dict]:
    """Read real failed/timed-out runs, including public repositories without a token."""
    repo_full_name = _validate_repo_full_name(repo_full_name)
    auth_token = token or settings.GITHUB_TOKEN
    headers = _github_rest_headers(auth_token) if auth_token else {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "smart-devops-assistant",
    }
    limit = min(max(limit, 1), 20)
    runs: list[dict[str, Any]] = []
    try:
        for conclusion in ("failure", "timed_out"):
            response = requests.get(
                f"{GITHUB_API_BASE_URL}/repos/{repo_full_name}/actions/runs",
                headers=headers, params={"status": conclusion, "per_page": limit},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code == 404:
                raise GitHubToolError(
                    "Repository not found or private. Configure GitHub access for private repositories."
                )
            if response.status_code == 401:
                raise GitHubToolError("GitHub credentials are invalid. Ask your admin to update GitHub access.")
            if response.status_code == 403:
                raise GitHubToolError("GitHub denied access or its API rate limit was reached. Try again later.")
            if response.status_code != 200:
                raise GitHubToolError(f"Unable to load failed workflow runs: GitHub returned {response.status_code}.")
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
                raise GitHubToolError("GitHub returned an invalid workflow run response.")
            runs.extend(
                run for run in payload["workflow_runs"] if run.get("conclusion") in {"failure", "timed_out"}
            )
    except (requests.RequestException, ValueError) as exc:
        raise GitHubToolError("Could not load GitHub workflow runs. Check connectivity and try again.") from exc
    runs.sort(key=lambda run: (run.get("created_at") or "", run.get("id") or 0), reverse=True)
    return runs[:limit]


def _append_limited(parts: list[str], text: str, remaining_chars: int) -> int:
    """Append text up to the remaining character budget."""
    if remaining_chars <= 0:
        return 0
    clipped = text[:remaining_chars]
    parts.append(clipped)
    return remaining_chars - len(clipped)


def _extract_logs_from_zip(content: bytes, text_limit: int) -> str:
    """Extract and clean text logs from a GitHub Actions zip payload."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise GitHubToolError("Unable to extract workflow logs: GitHub returned an invalid zip file.") from exc

    parts: list[str] = []
    remaining_chars = text_limit
    extracted_files = 0

    try:
        names = sorted(name for name in archive.namelist() if not name.endswith("/"))
        for name in names:
            if extracted_files >= WORKFLOW_LOG_FILE_LIMIT or remaining_chars <= 0:
                break

            try:
                raw = archive.read(name)
            except (KeyError, RuntimeError, zipfile.BadZipFile) as exc:
                raise GitHubToolError(f"Unable to extract workflow logs: failed reading '{name}'.") from exc

            if not raw:
                continue

            text = raw.decode("utf-8", errors="replace")
            text = _clean_log_text(text).strip()
            if not text:
                continue

            header = f"\n===== {name} =====\n"
            remaining_chars = _append_limited(parts, header, remaining_chars)
            remaining_chars = _append_limited(parts, text + "\n", remaining_chars)
            extracted_files += 1
    finally:
        archive.close()

    combined = "".join(parts).strip()
    if not combined:
        raise GitHubToolError("No workflow logs were available in the downloaded archive.")
    if remaining_chars <= 0:
        combined += "\n\n[Log output truncated]"
    return combined


def download_workflow_logs(repo_full_name: str, run_id: int, *, token: str | None = None) -> str:
    """
    Download, extract, clean, and redact GitHub Actions logs for a workflow run.

    GitHub returns workflow run logs as a zip archive. This helper follows the
    redirect, extracts text files in deterministic order, strips ANSI escape
    sequences, redacts token-looking values, and caps the returned text size.
    """
    repo_full_name = _validate_repo_full_name(repo_full_name)
    if not run_id:
        raise GitHubToolError("Workflow run id is required.")

    url = f"{GITHUB_API_BASE_URL}/repos/{repo_full_name}/actions/runs/{int(run_id)}/logs"
    try:
        response = requests.get(
            url,
            headers=_github_rest_headers(token),
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=True,
        )
    except requests.Timeout as exc:
        raise GitHubToolError(
            f"Unable to download workflow logs for {repo_full_name} run {run_id}: request timed out."
        ) from exc
    except requests.RequestException as exc:
        logger.error(
            "github.workflow_logs.download_request_failed",
            repo=repo_full_name,
            run_id=run_id,
            error_type=exc.__class__.__name__,
        )
        raise GitHubToolError(
            f"Unable to download workflow logs for {repo_full_name} run {run_id}: network request failed."
        ) from exc

    _raise_for_log_response(response, repo_full_name, int(run_id))

    content_type = response.headers.get("Content-Type", "")
    if "zip" not in content_type.lower() and not response.content.startswith(b"PK"):
        raise GitHubToolError(
            f"Unable to download workflow logs for {repo_full_name} run {run_id}: GitHub did not return a log zip."
        )

    log_text = _extract_logs_from_zip(response.content, WORKFLOW_LOG_TEXT_LIMIT)
    logger.info(
        "github.workflow_logs.downloaded",
        repo=repo_full_name,
        run_id=run_id,
        log_chars=len(log_text),
    )
    return log_text


def _format_stack_summary(detected_stack: Mapping[str, Any]) -> str:
    project_count = len(detected_stack.get("detected_projects") or [])
    summary = (
        f"Detected stack: language={detected_stack.get('language', 'unknown')}, "
        f"framework={detected_stack.get('framework', 'unknown')}, "
        f"recommended_workflow={detected_stack.get('recommended_workflow', 'generic-ci')}, "
        f"project_dir={detected_stack.get('project_dir', '.')}, "
        f"detected_projects={project_count}."
    )
    warnings = detected_stack.get("ci_warnings") or []
    if isinstance(warnings, list) and warnings:
        warning_lines = ["", "Existing workflow compatibility warnings:"]
        for warning in warnings[:5]:
            if not isinstance(warning, Mapping):
                continue
            warning_lines.append(
                f"- {warning.get('path', 'workflow')}: {warning.get('issue', 'Review existing workflow.')}"
            )
        summary += "\n" + "\n".join(warning_lines)
    return summary


def get_default_branch(repo_full_name: str, repo: str | None = None, *, token: str | None = None) -> str:
    """Return a repository's default branch.

    Accepts either ``owner/repo`` or legacy ``owner, repo`` arguments.
    """
    repository = (
        _get_repo(repo_full_name, repo, token)
        if repo is not None
        else _get_repo_by_full_name(repo_full_name, token)
    )
    return repository.default_branch


def get_repo_tree(owner: str, repo: str, branch: str) -> list[str]:
    """Return repository file paths for a branch."""
    repository = _get_repo(owner, repo)
    try:
        tree = repository.get_git_tree(branch, recursive=True)
        return sorted(item.path for item in tree.tree if getattr(item, "type", "") == "blob")
    except GithubException as exc:
        raise GitHubToolError(_github_error_message(exc, "Unable to read repository tree")) from exc


def get_repository_tree(repo_full_name: str, branch: str | None = None, *, token: str | None = None) -> list[str]:
    """
    Return recursive repository file paths for owner/repo.

    If branch is omitted, the repository default branch is used. Private
    repositories are supported through the configured GitHub token.
    """
    repo_full_name = _validate_repo_full_name(repo_full_name)
    try:
        repository = _get_client(token).get_repo(repo_full_name)
        target_branch = (branch or repository.default_branch or "").strip()
        if not target_branch:
            raise GitHubToolError(f"Unable to read repository tree for {repo_full_name}: branch is required.")

        tree = repository.get_git_tree(target_branch, recursive=True)
        files = sorted(item.path for item in tree.tree if getattr(item, "type", "") == "blob")
        logger.info(
            "github.repository_tree.scanned",
            repo=repo_full_name,
            branch=target_branch,
            file_count=len(files),
        )
        return files
    except GitHubToolError:
        raise
    except GithubException as exc:
        raise GitHubToolError(_github_error_message(exc, "Unable to read repository tree")) from exc


def get_file_content(repo_full_name: str, path: str, branch: str | None = None, *, token: str | None = None) -> dict:
    """
    Return UTF-8 text content for one file in a repository.

    The helper only reads repository content. Write operations still go through
    create_or_update_file(), which refuses direct writes to main/master.
    """
    repo_full_name = _validate_repo_full_name(repo_full_name)
    if not path.strip():
        raise GitHubToolError("Repository file path is required.")

    try:
        repository = _get_repo_by_full_name(repo_full_name, token)
        target_branch = (branch or repository.default_branch or "").strip()
        if not target_branch:
            raise GitHubToolError(f"Unable to read file '{path}' from {repo_full_name}: branch is required.")

        content_file = repository.get_contents(path, ref=target_branch)
        if isinstance(content_file, list):
            raise GitHubToolError(f"Unable to read file '{path}' from {repo_full_name}: path is a directory.")

        raw = getattr(content_file, "decoded_content", None)
        if raw is None:
            encoded = getattr(content_file, "content", None)
            if isinstance(encoded, str):
                try:
                    raw = base64.b64decode(encoded, validate=False)
                except Exception:
                    raw = encoded.encode("utf-8")
            else:
                raise GitHubToolError(f"Unable to read file '{path}' from {repo_full_name}: no text content found.")

        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        return {
            "path": path,
            "branch": target_branch,
            "content": text,
            "sha": getattr(content_file, "sha", None),
        }
    except GitHubToolError:
        raise
    except GithubException as exc:
        raise GitHubToolError(_github_error_message(exc, f"Unable to read file '{path}'")) from exc


def get_repository_analysis_inputs(
    repo_full_name: str,
    branch: str | None = None,
    *,
    token: str | None = None,
) -> dict[str, list[str]]:
    """
    Return repository paths plus safe content snapshots for stack/risk analysis.

    Tree paths are enough for many stacks, but manifest and workflow contents are
    needed to detect scripts, frameworks, package managers, and existing CI
    actions that can fail because of repository settings.
    """
    files = get_repository_tree(repo_full_name, branch, token=token)
    analysis_inputs = list(files)

    for path in _analysis_snapshot_paths(files):
        try:
            file_result = get_file_content(repo_full_name, path, branch, token=token)
        except GitHubToolError as exc:
            logger.warning("github.analysis_snapshot.skipped", path=path, error=str(exc))
            continue

        content = str(file_result.get("content") or "")
        if not content.strip():
            continue
        cleaned = _clean_log_text(content)[:ANALYSIS_SNAPSHOT_TEXT_LIMIT]
        analysis_inputs.append(f"{path}\n{cleaned}")

    return {"files": files, "analysis_inputs": analysis_inputs}


def _analysis_snapshot_paths(files: list[str]) -> list[str]:
    selected: list[str] = []
    for path in files:
        lower = path.lower()
        basename = lower.rsplit("/", 1)[-1]
        is_workflow = lower.startswith(".github/workflows/") and lower.endswith((".yml", ".yaml"))
        is_manifest = basename in _ANALYSIS_MANIFEST_NAMES
        is_source_hint = basename in _ANALYSIS_SOURCE_NAMES and lower.endswith(".py")

        if is_workflow or is_manifest or is_source_hint:
            selected.append(path)

        if len(selected) >= ANALYSIS_SNAPSHOT_FILE_LIMIT:
            break
    return selected


def create_branch(
    repo_full_name: str,
    base_branch: str,
    new_branch: str,
    legacy_new_branch: str | None = None,
    *,
    token: str | None = None,
) -> dict:
    """
    Create a new branch from a base branch. Existing branches are not reused.

    Accepts either ``owner/repo, base_branch, new_branch`` or legacy
    ``owner, repo, base_branch, new_branch`` arguments.
    """
    if legacy_new_branch is not None:
        repository = _get_repo(repo_full_name, base_branch, token)
        base_branch, new_branch = new_branch, legacy_new_branch
    else:
        repository = _get_repo_by_full_name(repo_full_name, token)

    if new_branch in {"main", "master"}:
        raise GitHubToolError("Refusing to create or write to main/master for generated workflow changes.")

    try:
        try:
            repository.get_git_ref(f"heads/{new_branch}")
            raise GitHubToolError(f"Branch '{new_branch}' already exists. Choose a new branch name.")
        except GithubException as exc:
            if getattr(exc, "status", None) != 404:
                raise

        base_ref = repository.get_git_ref(f"heads/{base_branch}")
        created = repository.create_git_ref(
            ref=f"refs/heads/{new_branch}",
            sha=base_ref.object.sha,
        )
        logger.info("github.branch.created", repo=repository.full_name, branch=new_branch, base_branch=base_branch)
        return {"branch": new_branch, "sha": created.object.sha}
    except GitHubToolError:
        raise
    except GithubException as exc:
        raise GitHubToolError(_github_error_message(exc, "Unable to create branch")) from exc


def create_or_update_file(
    repo_full_name: str,
    branch: str,
    path: str,
    content: str,
    commit_message: str,
    legacy_commit_message: str | None = None,
    *,
    overwrite: bool = False,
    token: str | None = None,
) -> dict:
    """
    Create a file on a branch, or update it only when overwrite=True.

    This default keeps generated workflows from accidentally replacing an
    existing repository file.
    """
    if legacy_commit_message is not None:
        owner = repo_full_name
        repo = branch
        branch = path
        path = content
        content = commit_message
        commit_message = legacy_commit_message
        repository = _get_repo(owner, repo, token)
    else:
        repository = _get_repo_by_full_name(repo_full_name, token)

    if branch in {"main", "master"}:
        raise GitHubToolError("Refusing to commit directly to main/master.")

    try:
        try:
            existing = repository.get_contents(path, ref=branch)
        except GithubException as exc:
            if getattr(exc, "status", None) != 404:
                raise
            result = repository.create_file(
                path=path,
                message=commit_message,
                content=content,
                branch=branch,
            )
            logger.info("github.file.created", repo=repository.full_name, branch=branch, path=path)
            return {"path": path, "sha": result["content"].sha, "action": "created"}

        if not overwrite:
            raise GitHubToolError(
                f"File '{path}' already exists on branch '{branch}'. "
                "Pass overwrite=True only when replacement is explicitly intended."
            )

        result = repository.update_file(
            path=path,
            message=commit_message,
            content=content,
            sha=existing.sha,
            branch=branch,
        )
        logger.info("github.file.updated", repo=repository.full_name, branch=branch, path=path)
        return {"path": path, "sha": result["content"].sha, "action": "updated"}
    except GitHubToolError:
        raise
    except GithubException as exc:
        raise GitHubToolError(_github_error_message(exc, "Unable to create or update file")) from exc


def create_pull_request(
    repo_full_name: str,
    head_branch: str,
    base_branch: str,
    title: str,
    body: str,
    legacy_body: str | None = None,
    *,
    token: str | None = None,
) -> dict:
    """Open a pull request from head_branch into base_branch."""
    if legacy_body is not None:
        owner = repo_full_name
        repo = head_branch
        head_branch = base_branch
        base_branch = title
        title = body
        body = legacy_body
        repository = _get_repo(owner, repo, token)
    else:
        repository = _get_repo_by_full_name(repo_full_name, token)

    if head_branch in {"main", "master"}:
        raise GitHubToolError("Refusing to open a pull request from main/master for generated workflow changes.")

    try:
        pr = repository.create_pull(
            title=title,
            body=body,
            head=head_branch,
            base=base_branch,
        )
        logger.info(
            "github.pull_request.created",
            repo=repository.full_name,
            number=pr.number,
            head=head_branch,
            base=base_branch,
        )
        return {"number": pr.number, "html_url": pr.html_url, "head": head_branch, "base": base_branch}
    except GithubException as exc:
        raise GitHubToolError(_github_error_message(exc, "Unable to create pull request")) from exc


def _workflow_branch_name(repository, base_name: str = WORKFLOW_BRANCH) -> str:
    """Return a safe branch name, adding a timestamp when the default exists."""
    try:
        repository.get_git_ref(f"heads/{base_name}")
    except GithubException as exc:
        if getattr(exc, "status", None) == 404:
            return base_name
        raise
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{base_name}-{timestamp}-{uuid.uuid4().hex[:8]}"


def _create_workflow_pr_from_yaml(
    repo_full_name: str,
    workflow_yaml: str,
    detected_stack: Mapping[str, Any],
    *,
    overwrite_existing_workflow: bool = False,
    token: str | None = None,
) -> dict:
    """
    Create a branch, commit an AI-generated workflow, and open a PR.

    The workflow is committed to .github/workflows/ai-generated-ci.yml on a
    dedicated branch; main/master is never written directly.
    """
    repo_full_name = _validate_repo_full_name(repo_full_name)
    repository = _get_repo_by_full_name(repo_full_name, token)
    base_branch = repository.default_branch
    if base_branch in {"ai-cicd/setup-pipeline", WORKFLOW_BRANCH}:
        raise GitHubToolError("Default branch is not a safe PR base for generated workflow changes.")

    # Check before creating a branch so a refused replacement or empty diff
    # leaves no abandoned branch behind on repeated attempts.
    try:
        existing = repository.get_contents(WORKFLOW_PATH, ref=base_branch)
    except GithubException as exc:
        if getattr(exc, "status", None) != 404:
            raise GitHubToolError(_github_error_message(exc, "Unable to inspect existing workflow")) from exc
    else:
        content = getattr(existing, "decoded_content", None)
        if isinstance(content, bytes) and content.decode("utf-8").strip() == workflow_yaml.strip():
            raise GitHubToolError(
                "The generated workflow already matches the default branch. No new pull request is needed."
            )
        if not overwrite_existing_workflow:
            raise GitHubToolError(
                "The AI-generated workflow file already exists. Review and select "
                "'Replace existing AI-generated workflow file' to request an update."
            )

    branch_name = _workflow_branch_name(repository)

    create_branch(repo_full_name, base_branch, branch_name, token=token)
    file_result = create_or_update_file(
        repo_full_name,
        branch_name,
        WORKFLOW_PATH,
        workflow_yaml,
        "Add AI-generated CI workflow",
        overwrite=overwrite_existing_workflow,
        token=token,
    )
    pr_result = create_pull_request(
        repo_full_name,
        branch_name,
        base_branch,
        "Add AI-generated CI workflow",
        (
            "This PR adds an AI-generated GitHub Actions workflow at "
            f"`{WORKFLOW_PATH}`.\n\n{_format_stack_summary(detected_stack)}"
        ),
        token=token,
    )
    return {
        "base_branch": base_branch,
        "branch": branch_name,
        "path": WORKFLOW_PATH,
        "file": file_result,
        "pull_request": pr_result,
    }


def create_workflow_pr(
    repo_full_name: str,
    repo: str | None = None,
    workflow_yaml: str | None = None,
    detected_stack: dict | None = None,
    *,
    overwrite_existing_workflow: bool = False,
    token: str | None = None,
) -> dict:
    """
    Scan a repository, generate a workflow, commit it to a branch, and open a PR.

    New usage: ``create_workflow_pr("owner/repo")``.
    Legacy usage is kept for tests/tools:
    ``create_workflow_pr(owner, repo, workflow_yaml, detected_stack)``.
    """
    if repo is not None and workflow_yaml is not None and detected_stack is not None:
        return _create_workflow_pr_from_yaml(
            _repo_full_name(repo_full_name, repo),
            workflow_yaml,
            detected_stack,
            overwrite_existing_workflow=overwrite_existing_workflow,
            token=token,
        )

    normalized_repo = _validate_repo_full_name(repo_full_name)
    analysis = get_repository_analysis_inputs(normalized_repo, token=token)
    stack = detect_stack(analysis["analysis_inputs"])
    generated_yaml = generate_workflow(stack)
    result = _create_workflow_pr_from_yaml(
        normalized_repo,
        generated_yaml,
        stack,
        overwrite_existing_workflow=overwrite_existing_workflow,
        token=token,
    )
    return {
        "repo_full_name": normalized_repo,
        "detected_stack": stack,
        "branch": result["branch"],
        "base_branch": result["base_branch"],
        "workflow_path": WORKFLOW_PATH,
        "file": result["file"],
        "pull_request": result["pull_request"],
        "pull_request_url": result["pull_request"]["html_url"],
    }


def list_workflows(repo_full_name: str = "", *, token: str | None = None) -> str:
    """List all workflows in a GitHub repository."""
    repo_full_name = repo_full_name or _default_repo()
    try:
        repo = _get_client(token).get_repo(repo_full_name)
        workflows = repo.get_workflows()
        if workflows.totalCount == 0:
            return f"No workflows found in '{repo_full_name}'."
        lines = [f"- [{w.state}] {w.name} (id: {w.id})" for w in workflows]
        return "\n".join(lines)
    except GithubException as e:
        return f"GitHub API error: {e.data.get('message', str(e))}"


def trigger_workflow(
    repo_full_name: str = "",
    workflow_id: str = "",
    ref: str = "main",
    inputs: dict | None = None,
    *,
    token: str | None = None,
) -> str:
    """Trigger a GitHub Actions workflow_dispatch event."""
    repo_full_name = repo_full_name or _default_repo()
    try:
        repo = _get_client(token).get_repo(repo_full_name)
        workflow = repo.get_workflow(workflow_id)
        success = workflow.create_dispatch(ref=ref, inputs=inputs or {})
        if success:
            logger.info(
                "github.workflow.triggered",
                repo=repo_full_name, workflow=workflow_id, ref=ref,
            )
            return f"✅ Workflow '{workflow_id}' triggered on branch '{ref}' in '{repo_full_name}'."
        return "Failed to trigger workflow — create_dispatch returned False."
    except GithubException as e:
        return f"GitHub API error: {e.data.get('message', str(e))}"


def get_workflow_run_status(repo_full_name: str = "", run_id: int = 0, *, token: str | None = None) -> str:
    """Get status of a specific workflow run."""
    repo_full_name = repo_full_name or _default_repo()
    try:
        repo = _get_client(token).get_repo(repo_full_name)
        run = repo.get_workflow_run(run_id)
        return (
            f"Run #{run.run_number} — {run.name}\n"
            f"  Status     : {run.status}\n"
            f"  Conclusion : {run.conclusion or 'in progress'}\n"
            f"  Branch     : {run.head_branch}\n"
            f"  Started    : {run.created_at}\n"
            f"  URL        : {run.html_url}"
        )
    except GithubException as e:
        return f"GitHub API error: {e.data.get('message', str(e))}"


def list_recent_runs(repo_full_name: str = "", limit: int = 5, *, token: str | None = None) -> str:
    """List the most recent workflow runs for a repository."""
    repo_full_name = repo_full_name or _default_repo()
    try:
        repo = _get_client(token).get_repo(repo_full_name)
        runs = repo.get_workflow_runs()
        lines = []
        for run in list(runs)[:limit]:
            emoji = {"success": "✅", "failure": "❌", "cancelled": "⚠️"}.get(
                run.conclusion, "🔄"
            )
            lines.append(
                f"{emoji} #{run.run_number} [{run.status}] {run.name} — "
                f"{run.head_branch} ({run.created_at.strftime('%Y-%m-%d %H:%M')})"
            )
        return "\n".join(lines) if lines else "No workflow runs found."
    except GithubException as e:
        return f"GitHub API error: {e.data.get('message', str(e))}"


def get_repo_info(repo_full_name: str = "", *, token: str | None = None) -> str:
    """Return basic metadata about a GitHub repository."""
    repo_full_name = repo_full_name or _default_repo()
    try:
        repo = _get_client(token).get_repo(repo_full_name)
        return (
            f"📦 {repo.full_name}\n"
            f"  Description  : {repo.description or '(none)'}\n"
            f"  Default branch: {repo.default_branch}\n"
            f"  Stars         : {repo.stargazers_count}\n"
            f"  Open issues   : {repo.open_issues_count}\n"
            f"  Last push     : {repo.pushed_at}\n"
            f"  URL           : {repo.html_url}"
        )
    except GithubException as e:
        return f"GitHub API error: {e.data.get('message', str(e))}"
