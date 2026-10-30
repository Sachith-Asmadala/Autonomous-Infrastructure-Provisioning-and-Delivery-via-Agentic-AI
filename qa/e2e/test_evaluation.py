import json
from pathlib import Path

import pytest

from qa.e2e.pages.base import EvaluationPage, SettingsPage


@pytest.mark.case(
    'EVAL-01',
    'Evaluation',
    'Display stored model metrics',
    'Dataset count and accuracy match the historical metrics artifact.',
)
def test_stored_metrics(admin):
    artifact = Path(__file__).resolve().parents[2] / "backend/app/ml/reports/metrics.json"
    metrics = json.loads(artifact.read_text())
    page = EvaluationPage(admin.driver, admin.base_url).open()
    page.text("Dataset Size")
    page.text(f"{metrics['dataset_size']:,}")
    page.text(f"{metrics['accuracy'] * 100:.1f}%")
    page.text("Macro F1-score")


@pytest.mark.case(
    'EVAL-02',
    'Evaluation',
    'Normal user cannot access evaluation admin metrics',
    'Restricted page is shown.',
)
def test_evaluation_permission(member):
    member.open("/evaluation").text("Access restricted")


@pytest.mark.case(
    'SET-01',
    'Settings',
    'Backend status and invalid URL',
    'Connection status renders; invalid protocols cannot be saved.',
)
def test_settings_and_validation(member):
    page = SettingsPage(member.driver, member.base_url).open()
    page.text("Active Backend")
    page.fill('input[placeholder="http://192.168.1.10:8000"]', "file:///etc/passwd")
    page.click("Save")
    page.text("Invalid URL. Use http:// or https://.")
    page.fill('input[placeholder="http://192.168.1.10:8000"]', member.base_url)
    page.click("Test Connection")
    page.text("Connected. Backend is reachable")


@pytest.mark.case(
    'SET-02',
    'Settings',
    'Backend status failure',
    'Failed backend status produces understandable feedback.',
)
def test_settings_backend_failure(member, faults):
    faults({"/api/v1/health/status": "error"})
    SettingsPage(member.driver, member.base_url).open().text("Controlled QA backend failure.")
