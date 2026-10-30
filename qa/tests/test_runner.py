"""Safety and evidence behavior of the QA harness itself."""
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from qa.run import clean_environment, sanitize_reports, write_summary
from qa.zap.scan import scan


def test_qa_environment_does_not_inherit_production_connections(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic.invalid/production")
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-value-never-used")
    monkeypatch.setenv("VITE_DISABLE_AUTH", "true")
    env = clean_environment()
    assert env["DATABASE_URL"] == "sqlite+aiosqlite:///:memory:"
    assert env["GITHUB_TOKEN"] == "" and env["DISABLE_AUTH"] == "false"
    assert "VITE_DISABLE_AUTH" not in env


@pytest.mark.parametrize("url", [
    "https://public.example.com", "http://192.168.1.1", "http://127.0.0.1.attacker.invalid",
])
def test_scanner_refuses_nonlocal_targets(url, tmp_path):
    with pytest.raises(ValueError, match="local"):
        scan(url, tmp_path, {})


def test_scanner_records_unavailable_docker_as_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=FileNotFoundError))
    assert scan("http://127.0.0.1:8888", tmp_path, {})["status"] == "Blocked"
    assert not (tmp_path / "zap.json").exists()


@pytest.mark.parametrize("code,status", [(0, "Passed"), (1, "Failed"), (2, "Warning"), (3, "Blocked")])
def test_zap_exit_codes_remain_distinct(monkeypatch, tmp_path, code, status):
    (tmp_path / "zap.json").write_text(json.dumps({"site": []}))
    run = Mock(side_effect=[Mock(returncode=0), Mock(returncode=code)])
    monkeypatch.setattr(subprocess, "run", run)
    assert scan("http://127.0.0.1:8888", tmp_path, {})["status"] == status
    command = run.call_args.args[0]
    assert "zap-baseline.py" in command
    assert "-I" not in command  # Warnings must never be ignored.
    assert "zap-full-scan.py" not in command


def test_summary_does_not_turn_blocked_stage_into_pass(tmp_path):
    manifest = {"execution_date": "test-fixture", "commit_sha": "fixture-sha",
                "source_sha256": "fixture-source", "working_tree_modified": True}
    write_summary(tmp_path, manifest, {"zap": {"status": "Blocked", "reason": "Docker unavailable"}})
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["test_counts"] == {}
    assert summary["stages"]["zap"]["status"] == "Blocked"
    assert "Blocked" in (tmp_path / "summary.md").read_text()


def test_zap_config_does_not_hide_findings():
    config = Path(__file__).resolve().parents[1] / "zap/baseline.conf"
    assert not any("IGNORE" in line for line in config.read_text().splitlines() if not line.startswith("#"))
    for line in config.read_text().splitlines():
        if line and not line.startswith("#"):
            fields = line.split("\t")
            assert len(fields) >= 3, "ZAP requires tab-separated rule, action and description"
            assert fields[0].isdigit() and fields[1] in {"WARN", "FAIL", "INFO"}


def test_docker_desktop_uses_only_the_local_gateway(monkeypatch, tmp_path):
    monkeypatch.setattr("qa.zap.scan.platform.system", lambda: "Darwin")
    (tmp_path / "zap.json").write_text(json.dumps({"site": []}))
    run = Mock(side_effect=[Mock(returncode=0), Mock(returncode=0)])
    monkeypatch.setattr(subprocess, "run", run)
    result = scan("http://127.0.0.1:8888", tmp_path, {})
    command = run.call_args.args[0]
    assert command[command.index("-t") + 1] == "http://host.docker.internal:8888"
    assert "--network" not in command
    assert result["target"] == "http://host.docker.internal:8888"


def test_report_sanitization_removes_ephemeral_passwords_and_tokens(tmp_path):
    report = tmp_path / "selenium.html"
    report.write_text("synthetic-password ghp_syntheticfixture eyJmaXh0dXJl.cGF5bG9hZA.c2lnbmF0dXJl")
    sanitize_reports(tmp_path, {"QA_TEST_PASSWORD": "synthetic-password"})
    assert report.read_text() == "[REDACTED] [REDACTED] [REDACTED]"


def test_report_sanitization_can_replace_read_only_scanner_reports(tmp_path):
    report = tmp_path / "zap.md"
    report.write_text("synthetic-password scan warning")
    report.chmod(0o444)
    sanitize_reports(tmp_path, {"QA_TEST_PASSWORD": "synthetic-password"})
    assert report.read_text() == "[REDACTED] scan warning"
    assert report.stat().st_mode & 0o200
    assert not list(tmp_path.glob(".redacted-*"))


def test_qa_workflow_cannot_deploy_and_always_uploads_evidence():
    import yaml

    workflow = Path(__file__).resolve().parents[2] / ".github/workflows/quality-assurance.yml"
    config = yaml.load(workflow.read_text(), Loader=yaml.BaseLoader)
    assert set(config["on"]) == {"pull_request", "workflow_dispatch"}
    assert config["permissions"] == {"contents": "read"}
    for job in config["jobs"].values():
        assert job["timeout-minutes"]
        uploads = [step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@")]
        assert uploads and all(step["if"] == "always()" for step in uploads)
    text = workflow.read_text()
    assert "continue-on-error" not in text
    assert "secrets." not in text
    assert "deploy.yml" not in text


@pytest.mark.parametrize("runner_code,job_code", [(0, 0), (1, 1), (2, 2), (3, 0), (127, 127), (130, 130)])
def test_ci_step_only_accepts_the_documented_warning_exit(tmp_path, runner_code, job_code):
    import yaml

    workflow = Path(__file__).resolve().parents[2] / ".github/workflows/quality-assurance.yml"
    config = yaml.load(workflow.read_text(), Loader=yaml.BaseLoader)
    step = next(step for step in config["jobs"]["browser-security"]["steps"]
                if step.get("name", "").startswith("Execute Selenium"))
    executable = tmp_path / "backend/venv/bin/python"
    executable.parent.mkdir(parents=True)
    executable.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > invocation.txt\nexit "$QA_FIXTURE_EXIT"\n')
    executable.chmod(0o755)
    report = tmp_path / "qa/reports/latest/summary.json"
    report.parent.mkdir(parents=True)
    report.write_text('{"fixture": true, "zap": "Warning"}')
    original = report.read_bytes()
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=tmp_path, env=os.environ | {"QA_FIXTURE_EXIT": str(runner_code)},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == job_code, result.stderr
    assert ("::warning title=ZAP baseline findings::" in result.stdout) == (runner_code == 3)
    assert (tmp_path / "invocation.txt").read_text().splitlines() == ["-m", "qa.run", "--suite", "ui-security"]
    assert report.read_bytes() == original
