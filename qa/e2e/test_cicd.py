import pytest
import yaml

from qa.e2e.pages.base import CICDPage


@pytest.mark.case(
    'CICD-01',
    'CI/CD Assistant',
    'Known npm failure fixture',
    'Stored classifier predicts the fixture label and supplies a fix.',
)
def test_known_failure(member):
    page = CICDPage(member.driver, member.base_url).open()
    page.predict('npm ERR! Missing script: "test"')
    page.text("npm_missing_test_script")
    page.text("Suggested Fix")
    page.text("package.json")


@pytest.mark.case(
    'CICD-02',
    'CI/CD Assistant',
    'Empty input guard',
    'Empty logs and file lists disable submissions.',
)
def test_empty_inputs(member):
    page = CICDPage(member.driver, member.base_url).open()
    page.fill("#failure-log", "   ")
    page.fill("#repository-files", "")
    assert not page.element("#failure-log").get_attribute("value").strip()
    assert not member.driver.find_element("xpath", "//button[normalize-space(.)='Predict Failure']").is_enabled()
    assert not member.driver.find_element("xpath", "//button[normalize-space(.)='Generate Workflow']").is_enabled()


@pytest.mark.case(
    'CICD-03',
    'CI/CD Assistant',
    'Generate and parse workflow',
    'Displayed YAML defines real CI jobs for repository files.',
)
def test_generated_yaml(member):
    page = CICDPage(member.driver, member.base_url).open()
    page.generate(["package.json", "package-lock.json", "src/App.tsx"])
    page.text("Detected Stack")
    document = yaml.safe_load(page.element("#workflow pre code").text)
    assert document["jobs"]
    assert "actions/setup-node" in str(document)
