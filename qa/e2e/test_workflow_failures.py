import pytest

from qa.e2e.pages.base import FailuresPage


@pytest.mark.case(
    'FAIL-01',
    'Workflow Failures',
    'List, inspect and search failures',
    'Known category, confidence, details and search states render.',
)
def test_failure_details_and_search(member):
    page = FailuresPage(member.driver, member.base_url).open()
    page.text("npm_missing_test_script")
    page.text("82%")
    page.element('button[aria-controls="failure-00000000-0000-0000-0000-000000000014"]').click()
    page.text("Log Excerpt")
    page.text("Add a test script in package.json.")
    page.search("does-not-exist")
    page.text("No failures match your search.")
    page.search("qa/demo")
    page.text("npm_missing_test_script")


@pytest.mark.case(
    'FAIL-02',
    'Workflow Failures',
    'Empty saved failure list',
    'An actionable empty state appears.',
)
def test_failure_empty(member, faults):
    faults({"/api/v1/workflow-failures": "empty"})
    FailuresPage(member.driver, member.base_url).open().text("No workflow failures yet")


@pytest.mark.case(
    'FAIL-03',
    'Workflow Failures',
    'Failure API error',
    'Error text appears without breaking the page.',
)
def test_failure_api_error(member, faults):
    faults({"/api/v1/workflow-failures": "error"})
    FailuresPage(member.driver, member.base_url).open().text("Controlled QA backend failure.")
