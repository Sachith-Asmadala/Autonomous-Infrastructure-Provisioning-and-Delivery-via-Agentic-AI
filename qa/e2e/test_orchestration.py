import json

import pytest

from qa.e2e.pages.base import OrchestrationPage


@pytest.mark.case(
    'ORCH-01',
    'Orchestration',
    'Route supported commands',
    'Exactly the intended specialist appears with structured output.',
)
@pytest.mark.parametrize("message,context,agent", [
    ("generate CI workflow", {"files": ["package.json", "src/App.tsx"]}, "cicd_agent"),
    ("analyze this log", {"log_text": 'npm ERR! Missing script: "test"'}, "diagnosis_agent"),
    ("scan repository", {"repo_full_name": "qa/demo"}, "github_agent"),
    ("show running containers", {}, "cli_agent"),
])
def test_specialist_routes(member, message, context, agent):
    page = OrchestrationPage(member.driver, member.base_url).open()
    page.run(message, json.dumps(context))
    page.text(agent)
    page.text("Agent Result")
    page.text("Agent Trace")
    page.click("Run Agent")  # Repeatability: no live external operations.
    page.text(agent)


@pytest.mark.case(
    'ORCH-02',
    'Orchestration',
    'Invalid JSON context',
    'Malformed JSON is rejected before submission.',
)
def test_invalid_context(member):
    page = OrchestrationPage(member.driver, member.base_url).open()
    page.run("generate CI workflow", "{bad json")
    page.text("Context must be valid JSON.")


@pytest.mark.case(
    'ORCH-03',
    'Orchestration',
    'Unsupported command',
    'Unknown route returns safe feedback.',
)
def test_unsupported_command(member):
    page = OrchestrationPage(member.driver, member.base_url).open()
    page.run("compose a sonnet about clouds")
    page.text("I could not route this request")
    page.text("orchestration_agent")
