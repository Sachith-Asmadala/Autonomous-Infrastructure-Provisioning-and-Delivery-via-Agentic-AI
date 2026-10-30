"""Transport verification must fail closed; report export preserves provenance."""
import importlib.util
import json
import ssl
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from qa.export_evidence import export

spec = importlib.util.spec_from_file_location(
    "verify_https", Path(__file__).resolve().parents[2] / "scripts/verify_https.py",
)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


@pytest.mark.parametrize("origin", ["http://example.com", "https://user:secret@example.com", "https://host/path"])
def test_https_verifier_rejects_unsafe_origins(origin):
    with pytest.raises(ValueError):
        verifier.https_origin(origin)


def test_https_verifier_does_not_bypass_certificate_failure(monkeypatch):
    monkeypatch.setattr(verifier.socket, "create_connection", Mock(side_effect=ssl.SSLCertVerificationError("test")))
    result = verifier.verify("https://127.0.0.1")
    assert result["status"] == "Failed"
    assert result["credentials_sent"] is False
    assert result.get("certificate_verified") is not True


def test_export_keeps_actual_outcomes_and_hashes(tmp_path):
    source = tmp_path / "raw"
    source.mkdir()
    (source / "manifest.json").write_text(json.dumps({
        "run_id": "fixture", "commit_sha": "fixture-sha", "source_sha256": "fixture-source",
        "execution_date": "fixture",
    }))
    (source / "summary.json").write_text(json.dumps({"test_counts": {"Passed": 1}, "stages": {"zap": {
        "status": "Warning", "exit_code": 2,
    }}}))
    (source / "selenium.xml").write_text('<testsuite tests="1" failures="0"/>')
    archive = export(source, tmp_path / "published")
    with zipfile.ZipFile(archive) as bundle:
        provenance = json.loads(bundle.read("PROVENANCE.json"))
        assert provenance["test_counts"] == {"Passed": 1}
        assert provenance["stages"]["zap"]["status"] == "Warning"
        assert bundle.read("selenium.xml") == (source / "selenium.xml").read_bytes()
        assert provenance["files"]["selenium.xml"]["original_sha256"]
