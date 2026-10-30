import os
import uuid

import pytest
import requests
from selenium.webdriver.common.by import By

from qa.e2e.pages.base import ApprovalsPage


@pytest.mark.case(
    'HITL-01',
    'Approvals',
    'Inspect owned pending and expired reviews',
    'Pending decisions are available; expired and privileged approval controls are absent.',
)
def test_pending_expired_and_privileged_controls(member):
    page = ApprovalsPage(member.driver, member.base_url).open()
    pending = page.card("QA pending review")
    assert [b.text for b in pending.find_elements(By.TAG_NAME, "button")] == ["Approve", "Reject"]
    expired = page.card("QA expired review")
    assert "Expired — execution is blocked." in expired.text
    assert not expired.find_elements(By.TAG_NAME, "button")
    privileged = page.card("QA privileged review")
    assert not privileged.find_elements(By.TAG_NAME, "button")


@pytest.mark.case(
    'HITL-02',
    'Approvals',
    'Reviewer rejects isolated request',
    'Rejected request is cancelled and removed from the pending queue.',
)
def test_reject_request(admin):
    # Each reviewer test creates its own review, so it cannot consume another
    # scenario's seeded approval or depend on pytest collection order.
    with requests.Session() as client:
        login = client.post(admin.base_url + "/api/v1/auth/login", timeout=5, json={
            "email": "qa-admin@example.com", "password": os.environ["QA_TEST_PASSWORD"],
        })
        login.raise_for_status()
        created = client.post(admin.base_url + "/api/v1/repositories/create-workflow-pr", timeout=5,
                              json={"repo_full_name": "qa/rejection-" + uuid.uuid4().hex[:8]})
        created.raise_for_status()
        approval_id = created.json()["approval_id"]
    page = ApprovalsPage(admin.driver, admin.base_url).open()
    card = page.element(f'div[data-approval-id="{approval_id}"]')
    next(button for button in card.find_elements(By.TAG_NAME, "button") if button.text == "Reject").click()
    page.text("Rejected. The action was cancelled.")
    page.wait.until(lambda d: not d.find_elements(By.CSS_SELECTOR, f'[data-approval-id="{approval_id}"]'))


@pytest.mark.case(
    "HITL-03", "Approvals", "Approval expires while the page remains open",
    "Expiry becomes explicit and the decision controls disappear without refresh.",
)
def test_live_expiry(member):
    response = requests.post(member.base_url + "/__qa/expiry", timeout=5,
                             headers={"X-QA-Control": os.environ["QA_CONTROL_TOKEN"]})
    response.raise_for_status()
    page = ApprovalsPage(member.driver, member.base_url).open()
    card = page.card("QA review expiring soon")
    assert card.find_elements(By.TAG_NAME, "button")
    page.wait.until(lambda d: not page.card("QA review expiring soon").find_elements(By.TAG_NAME, "button"))
    assert "Expired — execution is blocked." in page.card("QA review expiring soon").text
