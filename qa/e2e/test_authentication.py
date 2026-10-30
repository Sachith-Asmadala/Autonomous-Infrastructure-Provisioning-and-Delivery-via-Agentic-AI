import os
import uuid

import pytest
from selenium.webdriver.common.by import By

from qa.e2e.pages.base import LoginPage, Page


@pytest.mark.case(
    'AUTH-01',
    'Authentication',
    'Login page and required fields',
    'Required empty fields prevent submission.',
)
def test_login_page_required_fields(driver, base_url):
    page = LoginPage(driver, base_url).open()
    page.text("Welcome back.")
    page.click("Sign in")
    assert driver.execute_script("return document.querySelector('#email').validity.valueMissing")
    assert driver.current_url.endswith("/login")


@pytest.mark.case(
    'AUTH-02',
    'Authentication',
    'Valid temporary account login',
    'Authenticated dashboard and navigation appear.',
)
def test_valid_login(member):
    member.text("qa-member")
    member.element('nav[aria-label="Main navigation"]')
    assert member.driver.current_url.endswith("/dashboard")


@pytest.mark.case(
    'AUTH-03',
    'Authentication',
    'Invalid password',
    'Login remains visible with an error alert.',
)
def test_invalid_login(driver, base_url):
    page = LoginPage(driver, base_url).login("qa-member@example.com", "invalid-synthetic-password")
    assert page.element('[role="alert"]').text
    assert driver.current_url.endswith("/login")


@pytest.mark.case(
    'AUTH-04',
    'Authentication',
    'Registration validation',
    'Malformed email and short username/password are invalid.',
)
def test_registration_validation(driver, base_url):
    page = Page(driver, base_url).open("/signup")
    page.fill("#username", "q")
    page.fill("#email", "not-an-email")
    page.fill("#password", "short")
    page.fill("#confirmation", "short")
    assert not driver.execute_script("return document.querySelector('form').checkValidity()")
    assert driver.execute_script("return document.querySelector('#email').validity.typeMismatch")


@pytest.mark.case(
    'AUTH-05',
    'Authentication',
    'Password confirmation mismatch',
    'Registration is stopped with a clear mismatch error.',
)
def test_password_confirmation(driver, base_url):
    page = Page(driver, base_url).open("/signup")
    page.fill("#username", "qa-new-user")
    page.fill("#email", "qa-new@example.com")
    page.fill("#password", os.environ["QA_TEST_PASSWORD"])
    page.fill("#confirmation", "different-synthetic-password")
    page.click("Create account")
    page.text("Passwords do not match.")


@pytest.mark.case(
    'AUTH-06',
    'Authentication',
    'Register disposable account',
    'New developer reaches their workspace.',
)
def test_registration_succeeds(driver, base_url):
    page = Page(driver, base_url).open("/signup")
    name = "qa-" + uuid.uuid4().hex[:12]
    for selector, value in [("#username", name), ("#email", name + "@example.com"),
                            ("#password", os.environ["QA_TEST_PASSWORD"]),
                            ("#confirmation", os.environ["QA_TEST_PASSWORD"])]:
        page.fill(selector, value)
    page.click("Create account")
    page.element('nav[aria-label="Main navigation"]')
    page.text(name)


@pytest.mark.case(
    'AUTH-07',
    'Authentication',
    'Logout invalidates session',
    'Protected pages return to login after logout.',
)
def test_logout(member):
    member.element('button[aria-label="Sign out"]').click()
    member.open("/diagnosis")
    member.text("Welcome back.")
    assert member.driver.current_url.endswith("/login")


@pytest.mark.case(
    'AUTH-08',
    'Authentication',
    'Protected unauthenticated URL',
    'Protected route redirects to login.',
)
@pytest.mark.parametrize("path", ["/dashboard", "/approvals", "/users"])
def test_protected_routes_redirect(driver, base_url, path):
    page = Page(driver, base_url).open(path)
    page.text("Welcome back.")
    assert driver.current_url.endswith("/login")


@pytest.mark.case(
    'AUTH-09',
    'Authentication',
    'Developer cannot open administration',
    'Restricted content is shown and admin navigation is absent.',
)
def test_unauthorized_admin_access(member):
    member.open("/users")
    member.text("Access restricted")
    assert not member.driver.find_elements(By.CSS_SELECTOR, 'nav a[href="/users"]')
