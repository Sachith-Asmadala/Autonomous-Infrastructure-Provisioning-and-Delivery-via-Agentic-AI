"""Tests for GitHub workflow PR helper functions."""
from __future__ import annotations

import io
import zipfile

import pytest
from github import GithubException

from app.tools import github_tool


class _Obj:
    def __init__(self, **values):
        self.__dict__.update(values)


class _FakeRef:
    def __init__(self, sha: str):
        self.object = _Obj(sha=sha)


class _FakeTree:
    def __init__(self, paths: list[str]):
        self.tree = [_Obj(path=path, type="blob") for path in paths]


class _FakePullRequest:
    number = 7
    html_url = "https://github.com/octo-org/demo-app/pull/7"


class _FakeRepo:
    full_name = "octo-org/demo-app"
    default_branch = "main"

    def __init__(self):
        self.refs = {"main": "base-sha"}
        self.files: dict[str, _Obj] = {}
        self.created_files: list[dict] = []
        self.updated_files: list[dict] = []
        self.pull_requests: list[dict] = []
        self.fail_create_pull: GithubException | None = None

    def get_git_ref(self, ref: str):
        branch = ref.removeprefix("heads/")
        if branch not in self.refs:
            raise GithubException(404, {"message": "Not Found"})
        return _FakeRef(self.refs[branch])

    def create_git_ref(self, ref: str, sha: str):
        branch = ref.removeprefix("refs/heads/")
        self.refs[branch] = sha
        return _FakeRef(sha)

    def get_git_tree(self, branch: str, recursive: bool = True):
        assert recursive is True
        assert branch in self.refs
        return _FakeTree(["README.md", "src/app.py", ".github/workflows/ci.yml"])

    def get_contents(self, path: str, ref: str):
        if path not in self.files:
            raise GithubException(404, {"message": "Not Found"})
        return self.files[path]

    def create_file(self, path: str, message: str, content: str, branch: str):
        created = _Obj(sha="new-file-sha")
        self.files[path] = created
        self.created_files.append({"path": path, "message": message, "content": content, "branch": branch})
        return {"content": created}

    def update_file(self, path: str, message: str, content: str, sha: str, branch: str):
        updated = _Obj(sha="updated-file-sha")
        self.files[path] = updated
        self.updated_files.append({"path": path, "message": message, "content": content, "sha": sha, "branch": branch})
        return {"content": updated}

    def create_pull(self, title: str, body: str, head: str, base: str):
        if self.fail_create_pull:
            raise self.fail_create_pull
        self.pull_requests.append({"title": title, "body": body, "head": head, "base": base})
        return _FakePullRequest()


class _FakeClient:
    def __init__(self, repo: _FakeRepo | None = None, error: GithubException | None = None):
        self.repo = repo
        self.error = error

    def get_repo(self, full_name: str):
        if self.error:
            raise self.error
        assert full_name == "octo-org/demo-app"
        return self.repo


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        content: bytes = b"",
        *,
        headers: dict[str, str] | None = None,
        json_payload: dict | None = None,
        text: str = "",
        reason: str = "OK",
    ):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {"Content-Type": "application/zip"}
        self._json_payload = json_payload
        self.text = text
        self.reason = reason

    def json(self):
        if self._json_payload is None:
            raise ValueError("no json")
        return self._json_payload


def _zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.fixture()
def fake_repo(monkeypatch):
    repo = _FakeRepo()
    monkeypatch.setattr(github_tool, "_gh_client", _FakeClient(repo))
    return repo


def test_get_default_branch_and_repo_tree(fake_repo):
    assert github_tool.get_default_branch("octo-org", "demo-app") == "main"

    tree = github_tool.get_repo_tree("octo-org", "demo-app", "main")

    assert tree == [".github/workflows/ci.yml", "README.md", "src/app.py"]


def test_get_repository_tree_uses_default_branch(fake_repo):
    tree = github_tool.get_repository_tree("octo-org/demo-app")

    assert tree == [".github/workflows/ci.yml", "README.md", "src/app.py"]


def test_get_repository_tree_uses_requested_branch(fake_repo):
    fake_repo.refs["feature/demo"] = "feature-sha"

    tree = github_tool.get_repository_tree("octo-org/demo-app", "feature/demo")

    assert tree == [".github/workflows/ci.yml", "README.md", "src/app.py"]


def test_get_repository_tree_rejects_invalid_repo_name():
    with pytest.raises(github_tool.GitHubToolError, match="owner/repo"):
        github_tool.get_repository_tree("not-a-full-name")


def test_create_workflow_pr_creates_branch_file_and_pr(fake_repo):
    result = github_tool.create_workflow_pr(
        "octo-org",
        "demo-app",
        "name: CI\n'on': {}\njobs: {}\n",
        {"language": "javascript", "framework": "react", "recommended_workflow": "node-ci"},
    )

    assert result["base_branch"] == "main"
    assert result["branch"] == "ai-cicd/setup-pipeline"
    assert result["path"] == ".github/workflows/ai-generated-ci.yml"
    assert fake_repo.refs["ai-cicd/setup-pipeline"] == "base-sha"
    assert fake_repo.created_files[0]["branch"] == "ai-cicd/setup-pipeline"
    assert fake_repo.created_files[0]["path"] == ".github/workflows/ai-generated-ci.yml"
    assert fake_repo.pull_requests[0]["head"] == "ai-cicd/setup-pipeline"
    assert fake_repo.pull_requests[0]["base"] == "main"
    assert "recommended_workflow=node-ci" in fake_repo.pull_requests[0]["body"]


def test_create_workflow_pr_scans_generates_branch_file_and_pr(fake_repo):
    result = github_tool.create_workflow_pr("octo-org/demo-app")

    assert result["repo_full_name"] == "octo-org/demo-app"
    assert result["detected_stack"]["language"] == "python"
    assert result["branch"] == "ai-cicd/setup-pipeline"
    assert result["workflow_path"] == ".github/workflows/ai-generated-ci.yml"
    assert result["pull_request_url"] == "https://github.com/octo-org/demo-app/pull/7"
    assert fake_repo.created_files[0]["path"] == ".github/workflows/ai-generated-ci.yml"
    assert "actions/setup-python@v5" in fake_repo.created_files[0]["content"]
    assert fake_repo.pull_requests[0]["title"] == "Add AI-generated CI workflow"


def test_create_workflow_pr_uses_timestamp_branch_when_default_exists(fake_repo, monkeypatch):
    fake_repo.refs["ai-cicd/setup-pipeline"] = "existing-sha"

    class _FixedDateTime:
        @classmethod
        def now(cls, tz=None):
            return _Obj(strftime=lambda fmt: "20260531120000")

    monkeypatch.setattr(github_tool, "datetime", _FixedDateTime)

    result = github_tool.create_workflow_pr("octo-org/demo-app")

    assert result["branch"].startswith("ai-cicd/setup-pipeline-20260531120000-")
    assert fake_repo.created_files[0]["branch"] == result["branch"]


def test_create_workflow_pr_can_overwrite_existing_generated_workflow(fake_repo):
    fake_repo.files[".github/workflows/ai-generated-ci.yml"] = _Obj(sha="existing-workflow-sha")

    result = github_tool.create_workflow_pr(
        "octo-org/demo-app",
        overwrite_existing_workflow=True,
    )

    assert result["file"]["action"] == "updated"
    assert fake_repo.updated_files[0]["branch"] == "ai-cicd/setup-pipeline"
    assert fake_repo.updated_files[0]["path"] == ".github/workflows/ai-generated-ci.yml"
    assert fake_repo.updated_files[0]["sha"] == "existing-workflow-sha"
    assert "actions/setup-python@v5" in fake_repo.updated_files[0]["content"]


def test_create_branch_rejects_existing_branch(fake_repo):
    fake_repo.refs["ai-cicd/setup-pipeline"] = "existing-sha"

    with pytest.raises(github_tool.GitHubToolError, match="already exists"):
        github_tool.create_branch("octo-org", "demo-app", "main", "ai-cicd/setup-pipeline")


def test_create_or_update_file_does_not_overwrite_by_default(fake_repo):
    fake_repo.files[".github/workflows/ai-generated-ci.yml"] = _Obj(sha="existing-file-sha")

    with pytest.raises(github_tool.GitHubToolError, match="already exists"):
        github_tool.create_or_update_file(
            "octo-org",
            "demo-app",
            "ai-cicd/setup-pipeline",
            ".github/workflows/ai-generated-ci.yml",
            "workflow",
            "Add workflow",
        )

    assert fake_repo.updated_files == []


def test_create_or_update_file_can_update_when_explicit(fake_repo):
    fake_repo.files["README.md"] = _Obj(sha="existing-file-sha")

    result = github_tool.create_or_update_file(
        "octo-org",
        "demo-app",
        "ai-cicd/setup-pipeline",
        "README.md",
        "updated",
        "Update README",
        overwrite=True,
    )

    assert result == {"path": "README.md", "sha": "updated-file-sha", "action": "updated"}
    assert fake_repo.updated_files[0]["sha"] == "existing-file-sha"


def test_invalid_token_error_is_clear(monkeypatch):
    monkeypatch.setattr(
        github_tool,
        "_gh_client",
        _FakeClient(error=GithubException(401, {"message": "Bad credentials"})),
    )

    with pytest.raises(github_tool.GitHubToolError, match="invalid GitHub token"):
        github_tool.get_default_branch("octo-org", "demo-app")


def test_insufficient_permission_error_is_clear(fake_repo):
    fake_repo.fail_create_pull = GithubException(403, {"message": "Resource not accessible by integration"})

    with pytest.raises(github_tool.GitHubToolError, match="insufficient GitHub permissions"):
        github_tool.create_pull_request(
            "octo-org",
            "demo-app",
            "ai-cicd/setup-pipeline",
            "main",
            "Add CI",
            "Body",
        )


def test_download_workflow_logs_extracts_cleans_and_redacts(monkeypatch):
    captured: dict = {}
    content = _zip_bytes(
        {
            "1_build.txt": "\x1b[31mnpm ERR! Missing script: test\x1b[0m\n",
            "2_secret.txt": "token ghp_abcdefghijklmnopqrstuvwxyz123456\n",
        }
    )

    def _fake_get(url: str, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        captured["allow_redirects"] = kwargs["allow_redirects"]
        return _FakeResponse(200, content)

    monkeypatch.setattr(github_tool.settings, "GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(github_tool.requests, "get", _fake_get)

    log_text = github_tool.download_workflow_logs("octo-org/demo-app", 123456789)

    assert captured["url"].endswith("/repos/octo-org/demo-app/actions/runs/123456789/logs")
    assert captured["headers"]["Authorization"] == "Bearer test-token"
    assert captured["allow_redirects"] is True
    assert "1_build.txt" in log_text
    assert "npm ERR! Missing script: test" in log_text
    assert "\x1b" not in log_text
    assert "ghp_" not in log_text
    assert "[REDACTED]" in log_text


def test_download_workflow_logs_rejects_missing_run_id(monkeypatch):
    monkeypatch.setattr(github_tool.settings, "GITHUB_TOKEN", "test-token")

    with pytest.raises(github_tool.GitHubToolError, match="Workflow run id is required"):
        github_tool.download_workflow_logs("octo-org/demo-app", 0)


def test_download_workflow_logs_reports_invalid_token(monkeypatch):
    def _fake_get(url: str, **kwargs):
        return _FakeResponse(
            401,
            headers={"Content-Type": "application/json"},
            json_payload={"message": "Bad credentials"},
            reason="Unauthorized",
        )

    monkeypatch.setattr(github_tool.settings, "GITHUB_TOKEN", "bad-token")
    monkeypatch.setattr(github_tool.requests, "get", _fake_get)

    with pytest.raises(github_tool.GitHubToolError, match="invalid GitHub token"):
        github_tool.download_workflow_logs("octo-org/demo-app", 123)


def test_download_workflow_logs_reports_rate_limit(monkeypatch):
    def _fake_get(url: str, **kwargs):
        return _FakeResponse(
            403,
            headers={"Content-Type": "application/json", "X-RateLimit-Remaining": "0"},
            json_payload={"message": "API rate limit exceeded"},
            reason="Forbidden",
        )

    monkeypatch.setattr(github_tool.settings, "GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(github_tool.requests, "get", _fake_get)

    with pytest.raises(github_tool.GitHubToolError, match="rate limit exceeded"):
        github_tool.download_workflow_logs("octo-org/demo-app", 123)


def test_download_workflow_logs_reports_bad_zip(monkeypatch):
    def _fake_get(url: str, **kwargs):
        return _FakeResponse(200, b"not a zip", headers={"Content-Type": "application/zip"})

    monkeypatch.setattr(github_tool.settings, "GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(github_tool.requests, "get", _fake_get)

    with pytest.raises(github_tool.GitHubToolError, match="invalid zip file"):
        github_tool.download_workflow_logs("octo-org/demo-app", 123)


def test_download_workflow_logs_reports_empty_archive(monkeypatch):
    def _fake_get(url: str, **kwargs):
        return _FakeResponse(200, _zip_bytes({}))

    monkeypatch.setattr(github_tool.settings, "GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(github_tool.requests, "get", _fake_get)

    with pytest.raises(github_tool.GitHubToolError, match="No workflow logs"):
        github_tool.download_workflow_logs("octo-org/demo-app", 123)


def test_list_failed_workflow_runs_reads_public_metadata_and_includes_timeouts(monkeypatch):
    monkeypatch.setattr(github_tool.settings, "GITHUB_TOKEN", "")
    calls = []

    class Response:
        status_code = 200

        def __init__(self, conclusion):
            self.conclusion = conclusion

        def json(self):
            return {"workflow_runs": [{"id": 1 if self.conclusion == "failure" else 2,
                                      "conclusion": self.conclusion, "created_at": "2026-10-08T00:00:00Z"}]}

    def request(url, **kwargs):
        assert url == "https://api.github.com/repos/owner/repo/actions/runs"
        assert "Authorization" not in kwargs["headers"]
        calls.append(kwargs["params"]["status"])
        return Response(kwargs["params"]["status"])
    monkeypatch.setattr(github_tool.requests, "get", request)
    runs = github_tool.list_failed_workflow_runs("owner/repo")
    assert calls == ["failure", "timed_out"] and [run["id"] for run in runs] == [2, 1]


@pytest.mark.parametrize("repo", ["owner/repo?token=x", "owner/../repo", "../repo", "owner/..", "owner/repo#frag"])
def test_github_repository_names_reject_path_and_query_injection(repo):
    with pytest.raises(github_tool.GitHubToolError):
        github_tool.list_failed_workflow_runs(repo)


def test_pasted_workflow_logs_redact_short_passwords_and_connection_strings():
    original = "PASSWORD=short-secret\nDATABASE_URL=postgresql://someone:private@db.example/test\nMissing test script"
    cleaned = github_tool.clean_workflow_log(original)
    assert "short-secret" not in cleaned and "someone:private" not in cleaned
    assert "Missing test script" in cleaned


def test_workflow_preflight_refuses_existing_file_before_branch_creation(fake_repo):
    fake_repo.files[github_tool.WORKFLOW_PATH] = _Obj(sha="existing", decoded_content=b"name: Existing CI")
    with pytest.raises(github_tool.GitHubToolError, match="Replace existing AI-generated workflow"):
        github_tool.create_workflow_pr("octo-org/demo-app")
    assert fake_repo.refs == {"main": "base-sha"}
    assert fake_repo.created_files == fake_repo.pull_requests == []


def test_workflow_preflight_refuses_no_changes_even_with_overwrite(fake_repo):
    yaml = "name: Existing CI\n"
    fake_repo.files[github_tool.WORKFLOW_PATH] = _Obj(sha="existing", decoded_content=yaml.encode())
    with pytest.raises(github_tool.GitHubToolError, match="No new pull request is needed"):
        github_tool.create_workflow_pr("octo-org", "demo-app", yaml, {}, overwrite_existing_workflow=True)
    assert fake_repo.refs == {"main": "base-sha"}
    assert fake_repo.updated_files == []


def test_workflow_retry_branch_names_do_not_collide_in_same_second(fake_repo):
    fake_repo.refs[github_tool.WORKFLOW_BRANCH] = "existing"
    first = github_tool._workflow_branch_name(fake_repo)
    second = github_tool._workflow_branch_name(fake_repo)
    assert first != second and first.startswith(github_tool.WORKFLOW_BRANCH + "-")
