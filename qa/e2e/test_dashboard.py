import pytest


@pytest.mark.case(
    'DASH-01',
    'Dashboard',
    'Dashboard data and refresh',
    'Cards and activity render and refresh completes.',
)
def test_dashboard_and_refresh(member):
    member.text("Your recent activity")
    member.text("auth_login")
    member.click("Refresh")
    member.text("auth_login")
    member.wait.until(lambda d: member.button("Refresh").is_enabled())


@pytest.mark.case(
    'DASH-02',
    'Dashboard',
    'Sidebar navigation',
    'Each visible link opens the correct page.',
)
@pytest.mark.parametrize("path,title", [
    ("/chat", "Agent Chat"), ("/multi-agent", "Multi-Agent Orchestration"),
    ("/diagnosis", "CI/CD Assistant"), ("/repository-setup", "Repository CI/CD Setup"),
    ("/workflow-failures", "Workflow Failures"), ("/approvals", "Your approval review queue"),
    ("/executions", "Your audit log"), ("/settings", "Settings"),
])
def test_sidebar_navigation(member, path, title):
    member.navigate(path)
    member.heading(title)


@pytest.mark.case(
    'DASH-03',
    'Dashboard',
    'Partial backend failure',
    'Dashboard explains the failure and retains navigation.',
)
def test_dashboard_error(member, faults):
    faults({"/api/v1/audit": "error"})
    member.open("/dashboard")
    member.text("Some of your activity could not be loaded.")
    member.element('nav[aria-label="Main navigation"]')
