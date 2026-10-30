"""Strict CSP must retain the existing Radix dialog/scroll behavior."""
import pytest
from selenium.webdriver.common.by import By


@pytest.mark.case(
    "CSP-01", "Security policy", "Radix dialog uses the response's authorized style nonce",
    "Administration dialog opens and its dynamically inserted styles carry the document nonce.",
)
def test_dialog_style_nonce(admin):
    admin.open("/users")
    nonce = admin.driver.find_element(By.CSS_SELECTOR, 'meta[name="csp-nonce"]').get_attribute("content")
    assert nonce and nonce != "__CSP_NONCE__"
    admin.click("Add member")
    admin.element('[role="dialog"]')
    admin.wait.until(lambda driver: driver.execute_script(
        "return Array.from(document.querySelectorAll('style')).some(s => s.nonce === arguments[0]);", nonce,
    ))
