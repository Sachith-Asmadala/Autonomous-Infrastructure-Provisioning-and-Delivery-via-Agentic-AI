"""Boundary/security regressions for the five source-code QA findings."""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.services import failure_prediction_service as prediction
from app.services.approval_policy_service import approval_response
from app.services.cicd_readiness_service import assess_cicd_readiness
from app.services.repo_analyzer import detect_stack
from app.models.models import ApprovalRequest
from app.tools import shell_tool


@pytest.mark.parametrize("filename", [
    ".env.example", "backend/.env.sample", "docs/environment.md", "private-key.example",
])
def test_readiness_templates_do_not_claim_secret_exposure(filename):
    files = ["requirements.txt", filename]
    findings = assess_cicd_readiness(files, detect_stack(files))["findings"]
    assert not any(f["severity"] == "critical" for f in findings)


@pytest.mark.parametrize("filename", [
    ".env", "backend/.env.production", "keys/id_rsa", "config/credentials.json",
])
def test_readiness_suspect_names_require_inspection_not_claimed_exposure(filename):
    files = ["requirements.txt", filename]
    findings = assess_cicd_readiness(files, detect_stack(files))["findings"]
    security = next(f for f in findings if f["category"] == "security")
    assert security["severity"] == "warning"
    assert "content" in security["detail"].lower()


@pytest.mark.parametrize("command", [
    "echoevil", "date --file=/etc/shadow", "ls -la /etc", "ps auxww --env", "hostname attacker",
    "journalctl -n 5 /etc/shadow", "journalctl -n -1", "journalctl -n 9999999",
    "systemctl status --root=/tmp", 'echo "unterminated', "pwd; whoami", "pwd\nwhoami",
    "echo $(whoami)", "echo secret > /tmp/file", "cat /var/log/syslog /etc/shadow",
    "journalctl -n ²", None, 123,
])
def test_shell_rejects_prefix_bypass_and_unbounded_arguments(monkeypatch, command):
    run = Mock()
    monkeypatch.setattr(shell_tool.subprocess, "run", run)
    assert "blocked" in shell_tool.execute_safe_shell_command(command).lower()
    run.assert_not_called()


@pytest.mark.parametrize("command", ["pwd", "df -h", "echo hello world", "journalctl -n 50", "systemctl status nginx"])
def test_shell_validated_commands_use_argv_without_a_shell(monkeypatch, command):
    run = Mock(return_value=Mock(stdout="safe output", stderr=""))
    monkeypatch.setattr(shell_tool.subprocess, "run", run)
    assert shell_tool.execute_safe_shell_command(command) == "safe output"
    assert isinstance(run.call_args.args[0], list)
    assert run.call_args.kwargs.get("shell", False) is False
    assert run.call_args.kwargs["timeout"] == 30


def test_shell_redacts_sensitive_values_in_results_and_logs(monkeypatch):
    token = "ghp_" + "synthetic_qa_token"
    run = Mock(return_value=Mock(stdout=f"token={token}", stderr=""))
    monkeypatch.setattr(shell_tool.subprocess, "run", run)
    assert token not in shell_tool.execute_safe_shell_command(f"echo token={token}")
    assert token not in shell_tool.execute_safe_shell_command(f"forbidden token={token}")
    assert token not in shell_tool._redact_command_for_log(f"echo token={token}")


@pytest.mark.parametrize("value", ["password='synthetic qa secret'", 'api_key="synthetic qa secret"'])
def test_shell_redacts_quoted_credentials(monkeypatch, value):
    monkeypatch.setattr(shell_tool.subprocess, "run", Mock(return_value=Mock(stdout=value, stderr="")))
    assert "synthetic qa secret" not in shell_tool.execute_safe_shell_command(f"echo {value}")
    assert "synthetic qa secret" not in shell_tool._redact_command_for_log(f"forbidden {value}")


@pytest.mark.parametrize("value", [123, [], {}, b"error"])
def test_prediction_rejects_non_text_service_inputs(value):
    with pytest.raises(ValueError, match="text"):
        prediction.predict_failure(value)


@pytest.mark.parametrize("probability", [float("nan"), float("inf"), -0.1, 1.1])
def test_prediction_does_not_report_invalid_probabilities(monkeypatch, probability):
    model = Mock()
    model.predict.return_value = ["unknown_failure"]
    model.predict_proba.return_value = [[probability]]
    monkeypatch.setattr(prediction, "_model", model)
    monkeypatch.setattr(prediction, "_fix_mapping", {})
    assert prediction.predict_failure("unrecognized compiler output")["confidence"] is None


def test_prediction_caches_model_and_preserves_low_confidence(monkeypatch, tmp_path):
    artifact = tmp_path / "model.joblib"
    artifact.touch()
    model = Mock()
    model.predict.return_value = ["unknown_failure"]
    model.predict_proba.return_value = [[0.2, 0.3, 0.5]]
    load = Mock(return_value=model)
    monkeypatch.setattr(prediction, "MODEL_PATH", artifact)
    monkeypatch.setattr(prediction, "_model", None)
    monkeypatch.setattr(prediction, "_fix_mapping", {})
    monkeypatch.setattr(prediction, "_load_joblib_file", load)
    for _ in range(2):
        result = prediction.predict_failure("unsupported log fixture")
        assert result["confidence"] == 0.5
        assert result["recommendation"]["safe_fix_available"] is False
    load.assert_called_once_with(artifact)


def test_prediction_corrupt_artifact_returns_controlled_unavailable_error(monkeypatch, tmp_path):
    artifact = tmp_path / "corrupt.joblib"
    artifact.write_bytes(b"not a valid serialized classifier")
    monkeypatch.setattr(prediction, "MODEL_PATH", artifact)
    monkeypatch.setattr(prediction, "_model", None)
    with pytest.raises(prediction.FailurePredictionUnavailable, match="could not be loaded"):
        prediction.predict_failure("ModuleNotFoundError: missing dependency")


def test_prediction_without_probability_support_reports_unavailable_confidence(monkeypatch):
    class LabelOnlyModel:
        def predict(self, logs):
            return ["unmapped_qa_label"]

    monkeypatch.setattr(prediction, "_model", LabelOnlyModel())
    monkeypatch.setattr(prediction, "_fix_mapping", {})
    result = prediction.predict_failure("unrecognized QA build output")
    assert result["confidence"] is None
    assert result["recommendation"]["safe_fix_available"] is False


def test_expired_approval_response_never_offers_decision():
    now = datetime.now(timezone.utc)
    record = ApprovalRequest(id="00000000-0000-0000-0000-000000000001", requested_by="qa",
                             tool_name="github_create_workflow_pr", action="Review", risk_level="high",
                             summary="Expired fixture", status="pending", created_at=now,
                             expires_at=now - timedelta(seconds=1))
    result = approval_response(record, {"username": "qa", "role": "admin"})
    assert result.can_approve is False
    assert result.can_reject is False


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"not json", b"[]", b"null", b'{"workflow_run": []}', b'{"repository": "bad"}'])
async def test_webhook_rejects_signed_malformed_payload(isolated_app_database, monkeypatch, body):
    from app.main import app
    secret = "synthetic-qa-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret)
    monkeypatch.setattr(settings, "GITHUB_APP_WEBHOOK_SECRET", "")
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/webhooks/github", content=body,
                                     headers={"X-Hub-Signature-256": signature, "X-GitHub-Event": "workflow_run"})
    assert response.status_code == 400
    assert "traceback" not in response.text.lower()


@pytest.mark.asyncio
async def test_webhook_invalid_signature_and_unsupported_event(isolated_app_database, monkeypatch):
    from app.main import app
    from app.api.routes import webhooks
    secret = "synthetic-qa-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret)
    monkeypatch.setattr(settings, "GITHUB_APP_WEBHOOK_SECRET", "")
    handler = Mock(side_effect=AssertionError("Unsupported events must not execute tools"))
    monkeypatch.setattr(webhooks, "_handle_failed_workflow_run", handler)
    body = b'{}'
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        invalid = await client.post("/api/v1/webhooks/github", content=body,
                                    headers={"X-Hub-Signature-256": "sha256=invalid"})
        assert invalid.status_code == 401
        valid = await client.post("/api/v1/webhooks/github", content=body,
                                  headers={"X-Hub-Signature-256": signature, "X-GitHub-Event": "ping"})
        assert valid.status_code == 200 and valid.json()["received"] is True
    handler.assert_not_called()
