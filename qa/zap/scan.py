"""Only qa.run may supply this scanner a verified local QA target."""
import json
import hashlib
import platform
import subprocess
from pathlib import Path
from urllib.parse import urlsplit


def scan(base_url, reports, env):
    target = urlsplit(base_url)
    if target.hostname not in {"127.0.0.1", "localhost", "::1"} or target.scheme != "http":
        raise ValueError("ZAP target must be the local disposable QA application.")
    reports = Path(reports)
    try:
        available = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                                   capture_output=True, text=True, timeout=20, env=env)
        if available.returncode:
            return {"status": "Blocked", "reason": "Docker daemon is unavailable; ZAP was not executed.",
                    "exit_code": available.returncode}
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "Blocked", "reason": "Docker is missing or unresponsive; ZAP was not executed."}
    image = "ghcr.io/zaproxy/zaproxy:stable"
    config = Path(__file__).with_name("baseline.conf").resolve()
    # Docker Desktop's host network is opt-in. Its built-in host gateway reaches
    # this same loopback-bound disposable app without changing Desktop settings.
    docker_network = ["--network", "host"]
    scan_url = base_url
    if platform.system() == "Darwin":
        docker_network = []
        scan_url = f"http://host.docker.internal:{target.port}"
    container_name = "agentic-qa-zap-" + hashlib.sha256(str(reports).encode()).hexdigest()[:12]
    command = ["docker", "run", "--rm", "--name", container_name, *docker_network, "--user", "0:0",
               "-v", f"{reports}:/zap/wrk:rw", "-v", f"{config}:/zap/config/baseline.conf:ro",
               image, "zap-baseline.py", "-t", scan_url, "-m", "1", "-T", "5",
               "-c", "/zap/config/baseline.conf", "-r", "zap.html", "-J", "zap.json",
               "-w", "zap.md"]
    with (reports / "zap.log").open("w") as log:
        try:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=600, env=env)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=20, env=env)
            return {"status": "Blocked", "reason": "ZAP exceeded its ten-minute environment timeout."}
    # A missing report is setup failure even if Docker unexpectedly returns 0.
    if not (reports / "zap.json").is_file():
        return {"status": "Blocked", "reason": "ZAP did not produce its JSON report; inspect zap.log.",
                "exit_code": result.returncode}
    status = {0: "Passed", 1: "Failed", 2: "Warning", 3: "Blocked"}.get(result.returncode, "Blocked")
    alerts = []
    for site in json.loads((reports / "zap.json").read_text()).get("site", []):
        for alert in site.get("alerts", []):
            alerts.append({"finding": alert.get("name"), "severity": alert.get("riskdesc"),
                           "endpoints": [i.get("uri") for i in alert.get("instances", [])],
                           "evidence": [i.get("evidence") for i in alert.get("instances", [])],
                           "remediation": alert.get("solution"), "reference": alert.get("reference"),
                           "false_positive_considerations": "Review endpoint context and the HTTP-only QA environment.",
                           "remediation_verified": False})
    (reports / "security-findings.json").write_text(json.dumps(alerts, indent=2) + "\n")
    return {"status": status, "exit_code": result.returncode, "image": image, "target": scan_url,
            "findings": len(alerts), "evidence": ["zap.html", "zap.json", "security-findings.json"]}
