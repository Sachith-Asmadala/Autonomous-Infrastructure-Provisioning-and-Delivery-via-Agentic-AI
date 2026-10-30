import pytest

from qa.e2e.pages.base import RepositoryPage


@pytest.mark.case(
    'REPO-01',
    'Repository Analysis',
    'Analyze isolated repository',
    'Stack, readiness score and recommendations render.',
)
def test_repository_scan(member):
    page = RepositoryPage(member.driver, member.base_url).open()
    page.analyze("qa/demo")
    page.text("Detected Stack")
    page.text("CI/CD Readiness")
    page.text("Grade")
    page.text("Node lockfile missing")


@pytest.mark.case(
    'REPO-02',
    'Repository Analysis',
    'Invalid repository input',
    'Invalid identifier shows validation feedback.',
)
def test_invalid_repository(member):
    page = RepositoryPage(member.driver, member.base_url).open()
    page.analyze("invalid-name")
    page.text("owner/repo")


@pytest.mark.case(
    'REPO-03',
    'Repository Analysis',
    'GitHub authentication error',
    'Controlled GitHub error is understandable.',
)
def test_github_auth_error(member):
    page = RepositoryPage(member.driver, member.base_url).open()
    page.analyze("qa/auth-error")
    page.text("GitHub authentication failed")


@pytest.mark.case(
    'REPO-04',
    'Repository Analysis',
    'Workflow PR approval gate',
    'Request requires human approval and has no PR result.',
)
def test_workflow_pr_requires_approval(member):
    page = RepositoryPage(member.driver, member.base_url).open()
    # This fixture has no pre-existing approval; qa/demo deliberately has one.
    page.analyze("qa/workflow-demo")
    page.text("Detected Stack")
    page.click("Create Workflow PR")
    page.text("Approval Required")
    page.absent("Pull Request Created")
