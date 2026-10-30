import os
import json
from pathlib import Path

import pytest
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from qa.e2e.pages.base import LoginPage, WorkspacePage


@pytest.fixture(scope="session")
def base_url():
    url = os.environ["QA_BASE_URL"]
    response = requests.get(url + "/__qa/ready", timeout=5)
    response.raise_for_status()
    assert response.json() == {"isolated_qa": True, "run_id": os.environ["QA_RUN_ID"]}
    return url


@pytest.fixture
def faults(base_url):
    def set_faults(mapping):
        response = requests.post(base_url + "/__qa/control", json=mapping, timeout=5,
                                 headers={"X-QA-Control": os.environ["QA_CONTROL_TOKEN"]})
        response.raise_for_status()
    set_faults({})
    yield set_faults
    set_faults({})


@pytest.fixture
def driver(base_url, faults):
    options = webdriver.ChromeOptions()
    # SPA readiness is checked by page-object waits. Waiting for every external
    # font/image during navigation makes browser setup depend on third parties.
    options.page_load_strategy = "eager"
    for argument in ("--headless=new", "--window-size=1440,1000", "--disable-dev-shm-usage", "--no-sandbox"):
        options.add_argument(argument)
    if os.environ.get("QA_CHROME_BINARY"):
        options.binary_location = os.environ["QA_CHROME_BINARY"]
    # Selenium Manager resolves a driver matching installed Chrome/Chromium.
    browser = webdriver.Chrome(options=options)
    browser.set_page_load_timeout(30)
    capabilities = browser.capabilities
    info = {key: capabilities.get(key) for key in ("browserName", "browserVersion", "platformName")}
    info["chromedriverVersion"] = capabilities.get("chrome", {}).get("chromedriverVersion")
    (Path(os.environ["QA_REPORT_DIR"]) / "browser.json").write_text(json.dumps(info, indent=2) + "\n")
    yield browser
    browser.quit()


@pytest.fixture
def member(driver, base_url):
    LoginPage(driver, base_url).login("qa-member@example.com", os.environ["QA_TEST_PASSWORD"])
    WebDriverWait(driver, 15).until(lambda d: d.find_elements(By.CSS_SELECTOR, 'nav[aria-label="Main navigation"]'))
    return WorkspacePage(driver, base_url)


@pytest.fixture
def admin(driver, base_url):
    LoginPage(driver, base_url).login("qa-admin@example.com", os.environ["QA_TEST_PASSWORD"])
    WebDriverWait(driver, 15).until(lambda d: d.find_elements(By.CSS_SELECTOR, 'nav[aria-label="Main navigation"]'))
    return WorkspacePage(driver, base_url)
