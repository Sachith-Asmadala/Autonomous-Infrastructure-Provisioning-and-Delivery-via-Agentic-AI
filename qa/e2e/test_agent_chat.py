import pytest
from selenium.webdriver.common.by import By

from qa.e2e.pages.base import ChatPage


@pytest.mark.case(
    'CHAT-01',
    'Agent Chat',
    'Submit request with deterministic response',
    'User message and fixture response appear.',
)
def test_chat_submission(member):
    page = ChatPage(member.driver, member.base_url).open()
    page.send("Explain my QA workflow")
    page.text("Explain my QA workflow")
    page.text("QA deterministic response:")


@pytest.mark.case(
    'CHAT-02',
    'Agent Chat',
    'Empty chat submission',
    'Send stays disabled for whitespace.',
)
def test_empty_chat(member):
    page = ChatPage(member.driver, member.base_url).open()
    page.fill('textarea[aria-label="Message the DevOps assistant"]', "   ")
    assert not page.element('button[aria-label="Send message"]').is_enabled()


@pytest.mark.case(
    'CHAT-03',
    'Agent Chat',
    'Agent failure',
    'Failure is displayed and composer recovers.',
)
def test_chat_failure(member):
    page = ChatPage(member.driver, member.base_url).open()
    page.send("[qa:error]")
    page.wait.until(lambda d: any(
        message in d.find_element(By.TAG_NAME, "body").text
        for message in ("Streaming error:", "Request failed:")
    ))
    page.wait.until(lambda d: page.element('textarea[aria-label="Message the DevOps assistant"]').is_enabled())
    page.send("Recover after failure")
    page.text("QA deterministic response:")


@pytest.mark.case(
    'CHAT-04',
    'Agent Chat',
    'Delayed response',
    'Pending send prevents duplicates and eventually completes.',
)
def test_delayed_response(member):
    page = ChatPage(member.driver, member.base_url).open()
    page.send("[qa:delay] explain workflow")
    assert not page.element('button[aria-label="Send message"]').is_enabled()
    page.text("QA deterministic response:")
    page.wait.until(lambda d: page.element('textarea[aria-label="Message the DevOps assistant"]').is_enabled())


@pytest.mark.case(
    "CHAT-05", "Agent Chat", "HTTP fallback API failure and recovery",
    "Backend error is visible and the composer accepts another request after recovery.",
)
def test_http_fallback_failure(member, faults):
    faults({"/api/v1/agent/chat": "error"})
    page = ChatPage(member.driver, member.base_url).open()
    page.text("HTTP fallback")
    page.send("Explain my workflow through HTTP")
    page.text("Request failed:")
    page.text("Controlled QA backend failure.")
    faults({})
    page.send("Retry my workflow request")
    page.text("QA deterministic response:")
