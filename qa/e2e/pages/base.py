"""Page objects use explicit waits and semantic labels/IDs, never CSS styling."""
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import StaleElementReferenceException


class Page:
    path = "/"

    def __init__(self, driver, base_url):
        self.driver = driver
        self.base_url = base_url
        self.wait = WebDriverWait(driver, 15, ignored_exceptions=(StaleElementReferenceException,))

    def open(self, path=None):
        self.driver.get(self.base_url + (path or self.path))
        return self

    def element(self, selector):
        return self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, selector)))

    def fill(self, selector, value):
        element = self.element(selector)
        # WebDriver clear alone does not consistently fire React change events.
        element.send_keys(Keys.COMMAND if self.driver.capabilities.get("platformName") == "mac" else Keys.CONTROL, "a")
        element.send_keys(Keys.BACKSPACE)
        if value:
            element.send_keys(value)
        return element

    def button(self, label):
        locator = (By.XPATH, f"//button[normalize-space(.)='{label}']")
        element = self.wait.until(EC.presence_of_element_located(locator))
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        return self.wait.until(EC.element_to_be_clickable(locator))

    def click(self, label):
        button = self.button(label)
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", button)
        button.click()

    def text(self, value):
        self.wait.until(lambda d: value.casefold() in d.find_element(By.TAG_NAME, "body").text.casefold())
        return value

    def absent(self, value):
        self.wait.until(lambda d: value.casefold() not in d.find_element(By.TAG_NAME, "body").text.casefold())


class LoginPage(Page):
    path = "/login"

    def login(self, email, password):
        self.open()
        self.wait.until(EC.element_to_be_clickable((By.ID, "email")))
        self.fill("#email", email)
        self.fill("#password", password)
        self.click("Sign in")
        return self


class WorkspacePage(Page):
    def heading(self, title):
        self.wait.until(lambda d: any(
            e.text.casefold().startswith(title.casefold())
            for e in d.find_elements(By.CSS_SELECTOR, "h1,h2")
        ))

    def navigate(self, path):
        link = self.element(f'nav[aria-label="Main navigation"] a[href="{path}"]')
        link.click()
        self.wait.until(lambda d: d.current_url.split("?")[0].endswith(path))


class ChatPage(WorkspacePage):
    path = "/chat"

    def send(self, message):
        self.fill('textarea[aria-label="Message the DevOps assistant"]', message)
        self.element('button[aria-label="Send message"]').click()


class OrchestrationPage(WorkspacePage):
    path = "/multi-agent"

    def run(self, message, context="{}"):
        self.fill("#agent-command", message)
        self.fill("#agent-context", context)
        self.click("Run Agent")


class CICDPage(WorkspacePage):
    path = "/diagnosis"

    def predict(self, log):
        self.fill("#failure-log", log)
        self.click("Predict Failure")

    def generate(self, files):
        self.fill("#repository-files", "\n".join(files))
        self.click("Generate Workflow")


class RepositoryPage(WorkspacePage):
    path = "/repository-setup"

    def analyze(self, repo):
        self.fill("#repo-full-name", repo)
        self.click("Scan Repository")


class FailuresPage(WorkspacePage):
    path = "/workflow-failures"

    def search(self, value):
        self.fill('[aria-label="Search workflow failures"]', value)


class ApprovalsPage(WorkspacePage):
    path = "/approvals"

    def card(self, summary):
        return self.wait.until(EC.visibility_of_element_located((
            By.XPATH, f"//div[@data-approval-id][.//p[normalize-space(.)='{summary}']]")))


class AuditPage(WorkspacePage):
    path = "/executions"


class EvaluationPage(WorkspacePage):
    path = "/evaluation"


class SettingsPage(WorkspacePage):
    path = "/settings"
