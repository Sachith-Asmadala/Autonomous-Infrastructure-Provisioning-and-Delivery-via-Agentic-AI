"""Read-only HTTPS/certificate/health verification. Never sends credentials."""
import argparse
import json
import socket
import ssl
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, build_opener


def https_origin(value):
    target = urlsplit(value)
    if (target.scheme != "https" or not target.hostname or target.username or target.password
            or target.query or target.fragment or target.path not in {"", "/"}):
        raise ValueError("Supply an HTTPS origin without credentials, path, query or fragment.")
    return target


class SameOriginRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        before, after = urlsplit(req.full_url), urlsplit(newurl)
        if after.scheme != "https" or after.netloc != before.netloc:
            raise ValueError("Refusing a redirect outside the verified HTTPS origin.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def verify(origin, timeout=10):
    target = https_origin(origin)
    result = {"origin": origin.rstrip("/"), "observed_at": datetime.now(timezone.utc).isoformat(),
              "credentials_sent": False, "status": "Failed"}
    context = ssl.create_default_context()
    try:
        with socket.create_connection((target.hostname, target.port or 443), timeout=timeout) as connection:
            with context.wrap_socket(connection, server_hostname=target.hostname) as secure:
                certificate = secure.getpeercert()
                result.update(tls_version=secure.version(), certificate_expires=certificate.get("notAfter"),
                              subject_alt_names=certificate.get("subjectAltName"), certificate_verified=True)
        opener = build_opener(HTTPSHandler(context=context), SameOriginRedirect())
        with opener.open(result["origin"] + "/api/v1/health", timeout=timeout) as response:
            health = json.loads(response.read(16384))
            if response.status != 200 or health.get("status") != "ok":
                raise ValueError("HTTPS health endpoint did not report status ok.")
            result.update(status="Passed", health_status=health["status"], http_status=response.status)
    except Exception as exc:
        result.update(error_type=type(exc).__name__, error=str(exc))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.origin)
    except ValueError as exc:
        parser.error(str(exc))
    document = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(document)
    print(document, end="")
    return 0 if result["status"] == "Passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
