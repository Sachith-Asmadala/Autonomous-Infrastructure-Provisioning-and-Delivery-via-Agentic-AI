"""Publish a small sanitized, checksummed archive of actual QA reports."""
import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path


REPORTS = {
    "manifest.json", "summary.json", "summary.md", "traceability.md", "browser.json",
    "selenium.html", "selenium.xml", "backend.xml", "security.xml", "qa-tools.xml",
    "zap.html", "zap.json", "security-findings.json", "header-observations.json",
    "npm-audit.json", "tls-profile-validation.json", "public-https-verification.json",
    "supplemental-checks.json",
}


def export(source, destination):
    source, destination = Path(source).resolve(), Path(destination)
    manifest = json.loads((source / "manifest.json").read_text())
    summary = json.loads((source / "summary.json").read_text())
    destination.mkdir(parents=True, exist_ok=True)
    files = {}
    contents = {}
    for name in sorted(REPORTS):
        path = source / name
        if not path.is_file():
            continue
        original = path.read_bytes()
        text = original.decode()
        text = re.sub(r"/Users/[^/\s<>\"']+/(?:Library/Caches/)?", "<local>/", text)
        text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[REDACTED]", text)
        text = re.sub(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]+\b", "[REDACTED]", text)
        if "-----BEGIN PRIVATE KEY-----" in text or "-----BEGIN RSA PRIVATE KEY-----" in text:
            raise ValueError(f"Refusing to publish private key material in {name}")
        contents[name] = text.encode()
        files[name] = {"original_sha256": hashlib.sha256(original).hexdigest(),
                       "published_sha256": hashlib.sha256(contents[name]).hexdigest()}
    provenance = {"run_id": manifest["run_id"], "commit_sha": manifest["commit_sha"],
                  "source_sha256": manifest["source_sha256"], "execution_date": manifest["execution_date"],
                  "test_counts": summary["test_counts"], "stages": summary["stages"], "files": files,
                  "redactions": ["Local user paths", "Recognizable JWT and GitHub tokens"],
                  "scope": "Actual reports; no reconstructed results or fabricated screenshots."}
    archive = destination / (manifest["run_id"] + ".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for name, content in contents.items():
            output.writestr(name, content)
        output.writestr("PROVENANCE.json", json.dumps(provenance, indent=2) + "\n")
    provenance["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination / (manifest["run_id"] + ".json")).write_text(json.dumps(provenance, indent=2) + "\n")
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(export(args.source, args.destination))


if __name__ == "__main__":
    main()
