import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from qa.e2e.pages.base import AuditPage


@pytest.mark.case(
    'AUDIT-01',
    'Audit History',
    'Owned audit records and statuses',
    "Own success/failure records are visible; other users' records are absent.",
)
def test_audit_ownership_and_status(member):
    page = AuditPage(member.driver, member.base_url).open()
    page.text("QA qa-member completed audit record")
    page.text("QA qa-member failed audit record")
    page.absent("QA qa-other completed audit record")
    assert "hashed_password" not in member.driver.find_element(By.TAG_NAME, "body").text
    assert "refresh_token" not in member.driver.find_element(By.TAG_NAME, "body").text


@pytest.mark.case(
    'AUDIT-02',
    'Audit History',
    'Filter execution status',
    'Filter shows only matching owned audit records.',
)
def test_audit_filter(member):
    page = AuditPage(member.driver, member.base_url).open()
    page.text("QA qa-member completed audit record")
    Select(page.element('select[aria-label="Filter by status"]')).select_by_value("failed")
    page.text("QA qa-member failed audit record")
    page.absent("QA qa-member completed audit record")


@pytest.mark.case(
    'AUDIT-03',
    'Audit History',
    'Admin actor search',
    'Exact actor search isolates the selected account.',
)
def test_admin_actor_search(admin):
    page = AuditPage(admin.driver, admin.base_url).open()
    page.fill('[aria-label="Actor username"]', "qa-other")
    page.element('button[aria-label="Filter by actor"]').click()
    page.text("QA qa-other completed audit record")
    page.absent("QA qa-member completed audit record")
