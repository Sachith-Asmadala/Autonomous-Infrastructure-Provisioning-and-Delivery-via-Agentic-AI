"""CI/CD readiness assessment derived from repository analysis."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypedDict


FindingSeverity = Literal["info", "warning", "critical"]


class ReadinessFinding(TypedDict):
    severity: FindingSeverity
    category: str
    title: str
    detail: str
    recommendation: str


class ReadinessReport(TypedDict):
    score: int
    grade: str
    summary: str
    strengths: list[str]
    findings: list[ReadinessFinding]
    recommended_next_actions: list[str]


def assess_cicd_readiness(files: list[str], stack: Mapping[str, Any]) -> ReadinessReport:
    """Return a practical CI/CD readiness score for supervisor/demo review."""
    normalized_files = [_path(file) for file in files]
    lower_files = [file.lower() for file in normalized_files]
    findings: list[ReadinessFinding] = []
    strengths: list[str] = []
    score = 100

    detected_projects = stack.get("detected_projects") if isinstance(stack.get("detected_projects"), list) else []
    ci_warnings = stack.get("ci_warnings") if isinstance(stack.get("ci_warnings"), list) else []

    if stack.get("recommended_workflow") == "generic-ci":
        score -= 25
        findings.append(
            _finding(
                "warning",
                "stack-detection",
                "No supported application stack detected",
                "The repository does not expose a Node, Python, Java, or Docker project manifest.",
                (
                    "Add a standard manifest such as package.json, requirements.txt, "
                    "pyproject.toml, pom.xml, or Dockerfile."
                ),
            )
        )
    else:
        strengths.append(f"Detected {stack.get('recommended_workflow')} workflow recommendation.")

    if detected_projects:
        strengths.append(f"Identified {len(detected_projects)} project area(s) for CI coverage.")
    else:
        score -= 10
        findings.append(
            _finding(
                "warning",
                "project-layout",
                "No concrete project directory identified",
                "The analyzer could not map repository files to a specific project directory.",
                (
                    "Keep application manifests close to source code so generated workflows "
                    "can use the correct working directory."
                ),
            )
        )

    if stack.get("has_existing_workflows"):
        strengths.append("Repository already contains GitHub Actions workflow files.")
    else:
        score -= 12
        findings.append(
            _finding(
                "info",
                "workflow-coverage",
                "No existing GitHub Actions workflow detected",
                "The repository appears to need an initial CI workflow.",
                "Create the generated workflow pull request and review it before merging.",
            )
        )

    if ci_warnings:
        score -= min(30, 12 * len(ci_warnings))
        for warning in ci_warnings[:5]:
            findings.append(
                _finding(
                    "warning",
                    "workflow-compatibility",
                    str(warning.get("path") or "Existing workflow needs review"),
                    str(warning.get("issue") or "Existing workflow may fail because of repository settings."),
                    str(warning.get("recommendation") or "Review existing workflow requirements before merging."),
                )
            )
    else:
        strengths.append("No known existing workflow compatibility issues were detected.")

    if stack.get("language") == "multi":
        strengths.append("Multi-project repository detected; generated CI can create one job per supported project.")

    score -= _dependency_penalty(lower_files, stack, findings, strengths)
    score -= _test_penalty(lower_files, stack, findings, strengths)
    score -= _docker_penalty(lower_files, stack, findings, strengths)
    score -= _secret_penalty(lower_files, findings)

    bounded_score = max(0, min(100, score))
    grade = _grade(bounded_score)
    actions = _next_actions(findings, stack)

    return {
        "score": bounded_score,
        "grade": grade,
        "summary": _summary(bounded_score, grade, findings),
        "strengths": strengths[:8],
        "findings": findings[:10],
        "recommended_next_actions": actions[:6],
    }


def _dependency_penalty(
    files: list[str],
    stack: Mapping[str, Any],
    findings: list[ReadinessFinding],
    strengths: list[str],
) -> int:
    package_manager = str(stack.get("package_manager") or "")
    has_package_json = any(file.endswith("package.json") for file in files)
    has_lockfile = any(
        file.endswith(("package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock"))
        for file in files
    )

    if has_package_json and has_lockfile:
        strengths.append("Node dependency lockfile is present for reproducible installs.")
        return 0
    if has_package_json and package_manager in {"npm", "pnpm", "yarn", "mixed"}:
        findings.append(
            _finding(
                "warning",
                "dependencies",
                "Node lockfile missing",
                "Node dependency installation can be less reproducible without a lockfile.",
                "Commit package-lock.json, pnpm-lock.yaml, or yarn.lock when the project uses Node dependencies.",
            )
        )
        return 8
    return 0


def _test_penalty(
    files: list[str],
    stack: Mapping[str, Any],
    findings: list[ReadinessFinding],
    strengths: list[str],
) -> int:
    language = str(stack.get("language") or "")
    has_tests = any(
        "/test" in file
        or file.startswith("test")
        or "/tests/" in file
        or file.endswith((".test.js", ".test.ts", ".spec.js", ".spec.ts", "test_app.py"))
        for file in files
    )
    if has_tests:
        strengths.append("Repository contains test files or test directories.")
        return 0
    if language in {"javascript", "python", "java", "multi"}:
        findings.append(
            _finding(
                "info",
                "tests",
                "No test files detected",
                "Generated CI will skip missing tests, but a stronger project should include automated tests.",
                "Add at least one smoke test so the CI workflow proves application behavior.",
            )
        )
        return 8
    return 0


def _docker_penalty(
    files: list[str],
    stack: Mapping[str, Any],
    findings: list[ReadinessFinding],
    strengths: list[str],
) -> int:
    has_dockerfile = any(file.endswith("dockerfile") for file in files)
    has_compose = any(
        file.endswith(("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"))
        for file in files
    )
    if has_dockerfile:
        strengths.append("Dockerfile detected for container build validation.")
        return 0
    if has_compose and not has_dockerfile:
        findings.append(
            _finding(
                "info",
                "containerization",
                "Compose file exists without a Dockerfile",
                "The generated Docker validation can validate Compose syntax, but may not build an image.",
                "Add a Dockerfile if the repository should demonstrate containerized delivery.",
            )
        )
        return 5
    if stack.get("has_docker"):
        strengths.append("Container configuration detected.")
    return 0


def _secret_penalty(files: list[str], findings: list[ReadinessFinding]) -> int:
    # File names are evidence for inspection, not proof of credential exposure.
    # Templates are intentionally committed and should not lower readiness.
    risky_files = []
    for file in files:
        name = file.rsplit("/", 1)[-1]
        if name.endswith((".example", ".sample", ".template", ".dist")):
            continue
        if (name == ".env" or name.startswith(".env.")
                or name in {"id_rsa", "id_ed25519", "credentials.json", "service-account.json"}
                or name.startswith("private-key")):
            risky_files.append(file)
    if not risky_files:
        return 0
    findings.append(
        _finding(
            "warning",
            "security",
            "Potential secret-bearing files detected",
            f"Inspect these file contents for secrets: {', '.join(risky_files[:3])}. "
            "Names alone do not establish credential exposure.",
            "Inspect the content; remove actual secrets from git and rotate credentials if exposure is confirmed. "
            "Use GitHub Actions secrets for credentials.",
        )
    )
    return 25


def _next_actions(findings: list[ReadinessFinding], stack: Mapping[str, Any]) -> list[str]:
    actions = [finding["recommendation"] for finding in findings]
    if stack.get("recommended_workflow") != "generic-ci":
        actions.insert(0, "Create or update the AI-generated workflow pull request and review the diff.")
    actions.append("Run the generated pull request once and feed any failed logs back into the Diagnosis Agent.")
    return _dedupe(actions)


def _summary(score: int, grade: str, findings: list[ReadinessFinding]) -> str:
    if score >= 85:
        return f"Repository is CI/CD ready for the MVP demo with grade {grade}."
    if score >= 70:
        return f"Repository is mostly ready, with {len(findings)} improvement area(s) before a clean demo."
    if score >= 50:
        return f"Repository needs CI/CD cleanup before it is a strong demo candidate. Grade {grade}."
    return f"Repository is high risk for automated CI/CD setup until key findings are fixed. Grade {grade}."


def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "E"


def _finding(
    severity: FindingSeverity,
    category: str,
    title: str,
    detail: str,
    recommendation: str,
) -> ReadinessFinding:
    return {
        "severity": severity,
        "category": category,
        "title": title,
        "detail": detail,
        "recommendation": recommendation,
    }


def _path(file: str) -> str:
    value = str(file).strip().replace("\\", "/").lower()
    path = value.splitlines()[0].split("::", 1)[0].strip()
    while path.startswith("./"):
        path = path[2:]
    return path


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
