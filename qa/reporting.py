"""Pytest evidence plugin shared by backend, security, and Selenium runs."""
import hashlib
import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest


def pytest_configure(config):
    config._qa_cases = {}


def pytest_collection_modifyitems(config, items):
    for item in items:
        marker = item.get_closest_marker("case")
        data = dict(zip(("id", "module", "scenario", "expected"), marker.args)) if marker else {}
        if data and hasattr(item, "callspec"):
            data["id"] += "-" + item.callspec.id
        config._qa_cases[item.nodeid] = {
            "test_id": data.get("id", "REG-" + hashlib.sha256(item.nodeid.encode()).hexdigest()[:12]),
            "module": data.get("module", item.path.stem),
            "scenario": data.get("scenario", item.name.replace("_", " ")),
            "expected": data.get("expected", "All assertions in the referenced automated test hold."),
            "actual": "Test collected; execution has not completed.",
            "status": "Blocked",
            "nodeid": item.nodeid,
            "evidence": os.environ.get("QA_REPORT_LABEL", "pytest") + ".xml",
            "execution_date": datetime.now(timezone.utc).isoformat(),
            "commit_sha": os.environ.get("QA_COMMIT_SHA", "unknown"),
        }


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    case = item.config._qa_cases[item.nodeid]
    if report.failed:
        case.update(status="Failed" if report.when == "call" or case["status"] == "Failed" else "Blocked",
                    actual=f"{report.when} phase failed; see pytest report.")
    elif report.skipped:
        case.update(status="Skipped", actual="Pytest skipped this case; see report for reason.")
    elif report.when == "call":
        case.update(status="Passed", actual="Executed; all test assertions passed.")
    if report.failed and "driver" in item.funcargs:
        driver = item.funcargs["driver"]
        directory = Path(os.environ["QA_REPORT_DIR"]) / "screenshots"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (case["test_id"].replace("/", "_") + ".png")
        try:
            # Never capture typed credentials, request context, or cookie stores.
            driver.execute_script("""
                document.querySelectorAll('input,textarea').forEach(e => {
                  e.value = ''; e.style.visibility = 'hidden';
                });
            """)
            screenshot = driver.get_screenshot_as_base64()
            path.write_bytes(base64.b64decode(screenshot))
            case["screenshot"] = "screenshots/" + path.name
            if item.config.pluginmanager.hasplugin("html"):
                from pytest_html import extras
                report.extras = getattr(report, "extras", []) + [extras.png(screenshot)]
        except Exception:
            case["screenshot"] = "Screenshot unavailable (browser/setup failure)."


@pytest.hookimpl(optionalhook=True)
def pytest_metadata(metadata):
    # pytest-html must not copy arbitrary environment or CI variables.
    metadata.clear()
    metadata["Revision"] = os.environ.get("QA_COMMIT_SHA", "unknown")


def pytest_sessionfinish(session, exitstatus):
    destination = os.environ.get("QA_REPORT_DIR")
    if destination:
        path = Path(destination)
        path.mkdir(parents=True, exist_ok=True)
        label = os.environ.get("QA_REPORT_LABEL", "pytest")
        (path / f"{label}-cases.json").write_text(json.dumps({
            "pytest_exit_code": int(exitstatus), "cases": list(session.config._qa_cases.values()),
        }, indent=2) + "\n")
