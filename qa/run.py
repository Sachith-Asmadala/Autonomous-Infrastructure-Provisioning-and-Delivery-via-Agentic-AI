"""Own services, environment, evidence, timeouts, and cleanup for every QA run."""
import argparse
import hashlib
import json
import os
import platform
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from qa.zap.scan import scan

ROOT = Path(__file__).resolve().parents[1]


def clean_environment():
    # Do not inherit database URLs, cloud tokens, LLM keys, .env files, or npm mode flags.
    allowed = {"PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "LANG", "LC_ALL",
               "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "QA_CHROME_BINARY", "DOCKER_HOST",
               "DOCKER_CONTEXT", "DOCKER_CONFIG"}
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env.update(PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / "backend")]),
               DATABASE_URL="sqlite+aiosqlite:///:memory:", ENVIRONMENT="test", DEBUG="false",
               DESKTOP_MODE="false", DISABLE_AUTH="false", ENABLE_HITL="true",
               DEFAULT_LLM_PROVIDER="test", MEMORY_BACKEND="database", REDIS_URL="redis://127.0.0.1:1/0",
               OPENAI_API_KEY="", ANTHROPIC_API_KEY="", GITHUB_TOKEN="", GITHUB_APP_PRIVATE_KEY="",
               GITHUB_APP_ID="", GITHUB_WEBHOOK_SECRET="", GITHUB_APP_WEBHOOK_SECRET="",
               SECRET_KEY=secrets.token_urlsafe(48), DEFAULT_ADMIN_PASSWORD=secrets.token_urlsafe(24),
               COOKIE_SECURE="false", COOKIE_SAMESITE="lax", PYTHONDONTWRITEBYTECODE="1")
    return env


def revision():
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    files = {}
    entries = subprocess.check_output(["git", "ls-files", "-s", "-z"], cwd=ROOT).decode()
    for entry in entries.split("\0"):
        if entry:
            metadata, name = entry.split("\t", 1)
            files[name] = "git-blob-sha1:" + metadata.split()[1]
    changed = subprocess.check_output(["git", "diff", "--name-only", "HEAD", "-z"], cwd=ROOT).decode()
    untracked = subprocess.check_output(["git", "ls-files", "-o", "--exclude-standard", "-z"], cwd=ROOT).decode()
    for name in sorted(set((changed + untracked).split("\0")) - {""}):
        path = ROOT / name
        if path.is_file() and not name.startswith("qa/reports/"):
            content = path.read_bytes()
            if len(content) != path.stat().st_size:
                raise RuntimeError(f"File is not fully available locally; hydrate it before QA: {name}")
            files[name] = "sha256:" + hashlib.sha256(content).hexdigest()
        elif not path.exists():
            files.pop(name, None)
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT))
    return {"commit_sha": sha, "working_tree_modified": dirty, "source_sha256": fingerprint,
            "source_files": files, "python": platform.python_version(), "platform": platform.platform(),
            "python_distribution_directories": sorted(
                p.name.removesuffix(".dist-info") for p in
                (Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}"
                 / "site-packages").glob("*.dist-info")),
            "node": subprocess.check_output(["node", "--version"], text=True).strip()}


def execute(label, command, cwd, env, reports, timeout=900):
    print(f"QA: running {label}", flush=True)
    started = time.monotonic()
    with (reports / f"{label}.log").open("w") as output:
        try:
            result = subprocess.run(command, cwd=cwd, env=env, stdout=output,
                                    stderr=subprocess.STDOUT, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"status": "Blocked", "reason": f"{label} setup/timeout: {type(exc).__name__}",
                    "evidence": f"{label}.log"}
    status = "Passed" if result.returncode == 0 else "Failed"
    if label in {"backend", "selenium", "security", "qa-tools"} and result.returncode >= 2:
        status = "Blocked"
    cases_path = reports / f"{label}-cases.json"
    if cases_path.exists() and result.returncode:
        outcomes = {c["status"] for c in json.loads(cases_path.read_text())["cases"]}
        if "Failed" in outcomes:
            status = "Failed"
        elif "Blocked" in outcomes:
            status = "Blocked"
    print(f"QA: {label}: {status} (exit {result.returncode})", flush=True)
    return {"status": status, "exit_code": result.returncode, "evidence": f"{label}.log",
            "duration_seconds": round(time.monotonic() - started, 2)}


def pytest_command(label, reports, paths, config):
    return [sys.executable, "-m", "pytest", "-c", str(ROOT / config), "-p", "qa.reporting",
            *[str(ROOT / p) for p in paths], "-q", "--tb=short", "-m", "not real_llm",
            f"--junitxml={reports / (label + '.xml')}", f"--html={reports / (label + '.html')}",
            "--self-contained-html"]


def sanitize_reports(reports, env):
    """Remove ephemeral credentials and recognizable bearer tokens before publishing."""
    secret_values = [env.get(key, "") for key in
                     ("QA_TEST_PASSWORD", "QA_CONTROL_TOKEN", "SECRET_KEY", "DEFAULT_ADMIN_PASSWORD")]
    patterns = [r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
                r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]+\b"]
    for path in reports.rglob("*"):
        if path.is_file() and path.suffix in {".html", ".json", ".xml", ".log", ".md", ".txt"}:
            content = path.read_text(errors="replace")
            for secret in secret_values:
                if secret:
                    content = content.replace(secret, "[REDACTED]")
            for pattern in patterns:
                content = re.sub(pattern, "[REDACTED]", content)
            # Docker may create root-owned, read-only scanner reports on Linux.
            # Replace through the runner-owned directory instead of opening the
            # original inode for writing; the published file belongs to us.
            replacement = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                                 prefix=".redacted-", delete=False) as output:
                    replacement = Path(output.name)
                    output.write(content)
                replacement.replace(path)
            finally:
                if replacement is not None:
                    replacement.unlink(missing_ok=True)


def write_summary(reports, manifest, stages):
    cases = []
    for path in sorted(reports.glob("*-cases.json")):
        cases.extend(json.loads(path.read_text())["cases"])
    counts = dict(Counter(case["status"] for case in cases))
    summary = {"execution_date": manifest["execution_date"], "revision": manifest["commit_sha"],
               "source_sha256": manifest["source_sha256"], "stages": stages, "test_counts": counts,
               "cases": cases}
    (reports / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    lines = ["# Actual QA execution", "", f"Execution date (UTC): {manifest['execution_date']}",
             f"Commit: `{manifest['commit_sha']}`", f"Working tree modified: {manifest['working_tree_modified']}",
             f"Exact source fingerprint: `{manifest['source_sha256']}` (see manifest.json)", "",
             "| Stage | Status | Evidence / reason |", "|---|---|---|"]
    for name, stage in stages.items():
        detail = stage.get('reason', stage.get('evidence', 'summary.json'))
        lines.append(f"| {name} | {stage['status']} | {detail} |")
    lines += ["", f"Executed case outcomes: {counts}", "", "Mock boundaries: LLM, GitHub, Docker and shell. "
              "Authentication, RBAC, database, trained classifier, orchestration, approvals and audit routes are real.",
              "Stored model metrics are historical artifacts; this run does not retrain or re-evaluate model accuracy.",
              "", "See traceability.md for individual test outcomes. Blocked stages are not passing evidence."]
    (reports / "summary.md").write_text("\n".join(lines) + "\n")
    columns = ["test_id", "module", "scenario", "expected", "actual", "status",
               "evidence", "execution_date", "commit_sha"]
    table = ["# Executed test traceability", "", "| " + " | ".join(columns) + " |",
             "|" + "---|" * len(columns)]
    for case in cases:
        table.append("| " + " | ".join(str(case[c]).replace("|", "\\|").replace("\n", " ") for c in columns) + " |")
    (reports / "traceability.md").write_text("\n".join(table) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["all", "backend", "browser", "security", "ui-security"], default="all")
    parser.add_argument("--no-zap", action="store_true", help="Explicitly record ZAP as Not Executed")
    args = parser.parse_args()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
    reports = ROOT / "qa" / "reports" / run_id
    reports.mkdir(parents=True)
    latest = reports.parent / "latest"
    if latest.is_symlink():
        latest.unlink()
    if not latest.exists():
        latest.symlink_to(run_id, target_is_directory=True)
    manifest = revision()
    manifest.update(execution_date=datetime.now(timezone.utc).isoformat(), run_id=run_id)
    (reports / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    stages = {}
    server = None
    server_log = None
    print(f"QA reports: {reports}", flush=True)
    with tempfile.TemporaryDirectory(prefix="agentic-qa-") as temporary:
        work = Path(temporary).resolve()
        (work / ".isolated-qa").touch()
        env = clean_environment()
        env.update(QA_TEMP_DIR=str(work), QA_REPORT_DIR=str(reports), QA_RUN_ID=run_id,
                   PYTHONPYCACHEPREFIX=str(work / "pycache"),
                   QA_TEST_PASSWORD=os.environ.get("QA_TEST_PASSWORD") or secrets.token_urlsafe(24),
                   QA_CONTROL_TOKEN=secrets.token_urlsafe(32), QA_COMMIT_SHA=manifest["commit_sha"])
        try:
            if args.suite in {"all", "backend"}:
                env["QA_REPORT_LABEL"] = "backend"
                command = pytest_command("backend", reports, ["backend/tests"], "backend/pytest.ini")
                command += ["--cov=app", f"--cov-report=xml:{reports / 'coverage.xml'}",
                            f"--cov-report=html:{reports / 'coverage'}", "--cov-report=term-missing"]
                stages["backend"] = execute("backend", command, work, env, reports)
                env["QA_REPORT_LABEL"] = "qa-tools"
                stages["qa-tools"] = execute("qa-tools", pytest_command(
                    "qa-tools", reports, ["qa/tests"], "qa/pytest.ini"), work, env, reports)
            if args.suite in {"all", "browser", "security", "ui-security"}:
                build_env = env | {"VITE_API_BASE_URL": "", "VITE_DESKTOP_MODE": "false",
                                   "VITE_DISABLE_AUTH": "false", "VITE_MOBILE_MODE": "false"}
                build_command = ["npm", "run", "build", "--", "--outDir", str(work / "frontend")]
                stages["frontend-build"] = execute(
                    "frontend-build", build_command, ROOT / "frontend", build_env, reports)
                if stages["frontend-build"]["status"] != "Passed":
                    raise RuntimeError("Frontend build failed; browser and scan services were not started.")
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", 0))
                    port = probe.getsockname()[1]
                env.update(DATABASE_URL=f"sqlite+aiosqlite:///{work / 'qa.db'}",
                           QA_BASE_URL=f"http://127.0.0.1:{port}", QA_FRONTEND_DIST=str(work / "frontend"))
                server_log = (reports / "server.log").open("w")
                server = subprocess.Popen([sys.executable, "-m", "uvicorn", "qa.server:app", "--host", "127.0.0.1",
                                           "--port", str(port), "--no-access-log"], cwd=work, env=env,
                                          stdout=server_log, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + 60
                while True:
                    try:
                        with urlopen(env["QA_BASE_URL"] + "/__qa/ready", timeout=2) as response:
                            ready = json.load(response)
                        assert ready == {"isolated_qa": True, "run_id": run_id}
                        with urlopen(env["QA_BASE_URL"] + "/health", timeout=2) as response:
                            assert json.load(response)["status"] == "ok"
                        with urlopen(env["QA_BASE_URL"], timeout=2) as response:
                            assert b'<div id="root"' in response.read()
                        break
                    except Exception:
                        if server.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError("Isolated service failed health checks; see server.log.")
                        time.sleep(0.2)
                stages["isolated-services"] = {"status": "Passed", "evidence": "server.log"}
                if args.suite in {"all", "browser", "ui-security"}:
                    env["QA_REPORT_LABEL"] = "selenium"
                    stages["selenium"] = execute("selenium", pytest_command(
                        "selenium", reports, ["qa/e2e"], "qa/pytest.ini"), work, env, reports)
                if args.suite in {"all", "security", "ui-security"}:
                    env["QA_REPORT_LABEL"] = "security"
                    stages["security"] = execute("security", pytest_command(
                        "security", reports, ["qa/security"], "qa/pytest.ini"), work, env, reports)
                stages["zap"] = ({"status": "Not Executed", "reason": "Explicit --no-zap option."}
                                 if args.no_zap else scan(env["QA_BASE_URL"], reports, env))
        except KeyboardInterrupt:
            stages["interrupted"] = {"status": "Blocked", "reason": "QA run was interrupted before completion."}
        except Exception as exc:
            stages["environment"] = {"status": "Blocked", "reason": str(exc)}
            for label in (["selenium"] if args.suite == "browser" else
                          ["security", "zap"] if args.suite == "security" else
                          ["selenium", "security", "zap"] if args.suite in {"all", "ui-security"} else []):
                stages.setdefault(label, {"status": "Blocked", "reason": "Application setup did not complete."})
        finally:
            if server is not None:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
            if server_log:
                server_log.close()
            write_summary(reports, manifest, stages)
            sanitize_reports(reports, env)
    print(json.dumps({name: value["status"] for name, value in stages.items()}, indent=2), flush=True)
    print(f"Evidence: {reports / 'summary.md'}", flush=True)
    statuses = {s["status"] for s in stages.values()}
    if "Failed" in statuses:
        return 1
    if "Blocked" in statuses:
        return 2
    return 3 if "Warning" in statuses else 0


if __name__ == "__main__":
    sys.exit(main())
