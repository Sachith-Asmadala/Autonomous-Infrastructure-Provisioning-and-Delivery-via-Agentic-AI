"""Tests for CI/CD readiness assessment."""
from __future__ import annotations

from app.services.cicd_readiness_service import assess_cicd_readiness
from app.services.repo_analyzer import detect_stack


def test_readiness_rewards_supported_project_with_workflow_tests_and_lockfile():
    files = [
        "package.json",
        "package-lock.json",
        "src/App.jsx",
        "tests/app.test.js",
        ".github/workflows/ci.yml",
        "Dockerfile",
    ]
    stack = detect_stack(files)

    report = assess_cicd_readiness(files, stack)

    assert report["score"] >= 85
    assert report["grade"] in {"A", "B"}
    assert any("workflow" in strength.lower() for strength in report["strengths"])
    assert report["recommended_next_actions"]


def test_readiness_flags_dependency_review_warning_and_missing_tests():
    files = ["package.json", ".github/workflows/security.yml"]
    stack = detect_stack(
        [
            *files,
            ".github/workflows/security.yml\n"
            "jobs:\n"
            "  dependency-review:\n"
            "    steps:\n"
            "      - uses: actions/dependency-review-action@v5\n",
        ]
    )

    report = assess_cicd_readiness(files, stack)

    assert report["score"] < 80
    categories = {finding["category"] for finding in report["findings"]}
    assert "workflow-compatibility" in categories
    assert "tests" in categories


def test_readiness_flags_secret_like_files_for_review():
    files = ["requirements.txt", "app/main.py", ".env"]
    stack = detect_stack(files)

    report = assess_cicd_readiness(files, stack)

    assert report["score"] <= 70
    assert any(finding["severity"] == "warning" and finding["category"] == "security"
               for finding in report["findings"])
    assert any("secret" in action.lower() for action in report["recommended_next_actions"])
