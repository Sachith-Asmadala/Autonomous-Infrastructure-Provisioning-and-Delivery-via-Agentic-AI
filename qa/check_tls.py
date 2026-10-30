"""Validate the real Nginx TLS template on loopback using an ephemeral test CA."""
import argparse
import http.client
import json
import os
import re
import secrets
import ssl
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def command(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=120, **kwargs)


def check(image, report):
    identity = "agentic-qa-tls-" + secrets.token_hex(6)
    frontend, backend = identity + "-frontend", identity + "-backend"
    result = {"observed_at": datetime.now(timezone.utc).isoformat(), "status": "Failed",
              "scope": "Loopback Docker fixture, not the EC2 deployment",
              "trust": "Ephemeral test CA trusted explicitly for positive test only", "checks": []}
    with tempfile.TemporaryDirectory(prefix="agentic-tls-") as directory:
        work = Path(directory)
        certdir = work / "certificates/live/127.0.0.1"
        certdir.mkdir(parents=True)
        acme = work / "webroot/.well-known/acme-challenge"
        acme.mkdir(parents=True)
        (acme / "fixture").write_text("isolated-acme-fixture")
        configuration = work / "backend.conf"
        configuration.write_text('server { listen 8000; location / { default_type application/json; '
                                 'return 200 \'{"status":"ok"}\'; } }\n')
        try:
            command(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                     "-keyout", str(certdir / "privkey.pem"), "-out", str(certdir / "fullchain.pem"),
                     "-subj", "/CN=Isolated QA", "-addext", "subjectAltName=IP:127.0.0.1"])
            command(["docker", "network", "create", identity])
            command(["docker", "run", "-d", "--rm", "--name", backend, "--network", identity,
                     "--network-alias", "backend", "-v", f"{configuration}:/etc/nginx/conf.d/default.conf:ro",
                     "nginx:alpine"])
            command(["docker", "run", "-d", "--rm", "--name", frontend, "--network", identity,
                     "-p", "127.0.0.1::80", "-p", "127.0.0.1::443", "-e", "APP_HOST=127.0.0.1",
                     "-e", "NGINX_ENVSUBST_FILTER=^APP_HOST$",
                     "-v", f"{ROOT / 'deploy/nginx-https.conf.template'}:/etc/nginx/templates/default.conf.template:ro",
                     "-v", f"{work / 'certificates'}:/etc/letsencrypt:ro",
                     "-v", f"{work / 'webroot'}:/var/www/acme:ro", image])
            tls_port = int(command(["docker", "port", frontend, "443/tcp"]).stdout.strip().rsplit(":", 1)[1])
            http_port = int(command(["docker", "port", frontend, "80/tcp"]).stdout.strip().rsplit(":", 1)[1])
            origin = f"https://127.0.0.1:{tls_port}"
            context = ssl.create_default_context(cafile=str(certdir / "fullchain.pem"))
            deadline = time.monotonic() + 30
            while True:
                try:
                    with urlopen(origin, context=context, timeout=3) as response:
                        body = response.read().decode()
                        assert response.status == 200
                        assert "Smart DevOps Assistant" in body
                        assert response.headers["X-Content-Type-Options"] == "nosniff"
                        assert response.headers["Strict-Transport-Security"] == "max-age=31536000"
                        nonce = re.search(r'name="csp-nonce" content="([^\"]+)"', body).group(1)
                        assert nonce != "__CSP_NONCE__"
                        assert f"'nonce-{nonce}'" in response.headers["Content-Security-Policy"]
                        assert "unsafe-inline" not in response.headers["Content-Security-Policy"]
                        break
                except Exception:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.2)
            result["checks"].append("Real Nginx serves application HTML over verified TLS with HSTS and nosniff")
            asset = re.search(r'src="(/assets/[^\"]+\.js)"', body).group(1)
            with urlopen(origin + asset, context=context, timeout=5) as response:
                assert response.headers["X-Frame-Options"] == "DENY"
                assert "immutable" in ", ".join(response.headers.get_all("Cache-Control", []))
            result["checks"].append("Static asset locations retain security headers and immutable cache policy")
            connection = http.client.HTTPConnection("127.0.0.1", http_port, timeout=5)
            connection.request("GET", "/example?check=1")
            redirect = connection.getresponse()
            assert redirect.status == 308
            assert redirect.headers["Location"] == "https://127.0.0.1/example?check=1"
            connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", http_port, timeout=5)
            connection.request("GET", "/.well-known/acme-challenge/fixture")
            challenge = connection.getresponse()
            assert challenge.status == 200 and challenge.read() == b"isolated-acme-fixture"
            connection.close()
            result["checks"].append("HTTP redirects canonically while ACME webroot challenges remain reachable")
            env = os.environ | {"SSL_CERT_FILE": str(certdir / "fullchain.pem")}
            verified = command([sys.executable, str(ROOT / "scripts/verify_https.py"), origin], env=env)
            result["verified_fixture"] = json.loads(verified.stdout)
            assert result["verified_fixture"]["status"] == "Passed"
            result["checks"].append("Production verification helper validates certificate, IP SAN and proxied health")
            untrusted_env = {k: v for k, v in os.environ.items() if k not in {"SSL_CERT_FILE", "SSL_CERT_DIR"}}
            rejected = subprocess.run([sys.executable, str(ROOT / "scripts/verify_https.py"), origin],
                                      env=untrusted_env, capture_output=True, text=True, timeout=20)
            assert rejected.returncode == 1
            assert json.loads(rejected.stdout)["error_type"] == "SSLCertVerificationError"
            result["checks"].append("Untrusted certificates fail; no insecure verification bypass")
            result["status"] = "Passed"
        except Exception as exc:
            result.update(error_type=type(exc).__name__, error=str(exc))
        finally:
            for name in (frontend, backend):
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)
            subprocess.run(["docker", "network", "rm", identity], capture_output=True, timeout=30)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "Passed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="agentic-qa-frontend-security:review")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    return check(args.image, args.report)


if __name__ == "__main__":
    raise SystemExit(main())
