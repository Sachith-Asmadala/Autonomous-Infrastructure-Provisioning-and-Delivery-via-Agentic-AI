# Security and reproducibility follow-up — 30 October 2026

The isolated OWASP ZAP baseline **completed**. No scan targeted EC2 or the public
application. The final scan returned **0 FAIL, 4 WARN categories, 64 PASS checks**:
5 alerts, comprising **1 Low and 4 Informational**, with no High or Medium alerts.
ZAP's exit code remains 2 (warnings), not a clean security pass.

| Actual execution | Result | Preserved reports |
|---|---|---|
| Initial completed baseline, `20261030T035657Z-f8a046` | 0 FAIL, 9 WARN categories, 59 PASS; 11 alerts | [HTML/JSON archive](qa-evidence/isolated-zap/20261030T035657Z-f8a046.zip) |
| Intermediate hardening scan, `20261030T041249Z-85c9ef` | 0 FAIL, 5 WARN categories, 63 PASS; one browser fixture race retained | [Actual archive](qa-evidence/isolated-zap/20261030T041249Z-85c9ef.zip) |
| Final scan, `20261030T044659Z-368bb5` | 0 FAIL, 4 WARN categories, 64 PASS; 12 controlled security tests passed | [HTML/JSON and findings](qa-evidence/security-followup/20261030T044659Z-368bb5.zip) |
| Final application suite, `20261030T044046Z-203962` | **454 passed**: 370 backend, 53 Selenium, 12 controlled security, 19 harness | [Actual HTML/XML/traceability archive](qa-evidence/security-followup/20261030T044046Z-203962.zip) |
| Additional verification | Lint, typing, production build, 23 Python and 20 JS workflow checks passed; npm audit **0 vulnerabilities** | Supplemental results in the application archive |
| Actual Nginx HTTPS overlay | Verified TLS 1.3, certificate/IP identity, redirect, ACME challenge, static headers, proxied health; untrusted certificate rejected | Local fixture result in the application archive |
| Public `https://54.66.191.38` | **Connection refused**, no credentials sent | Public verification JSON in the application archive |

Remediations add CSP with per-response style nonces, frame/content-type and
cross-origin policies, private-response cache controls, and self-hosted fonts.
Dependency updates remove the 18 previously reported npm advisories. Health/error
responses no longer reveal the model's absolute filesystem path. The real browser
suite verifies dialog styling under CSP and preserves approval/RBAC checks.
Statement coverage was 3,563 / 4,907 (72.61%).

The remaining Low finding is the literal `192.168.1.10:8000` in a LAN connection
example, not a discovered EC2 address. Informational observations concern bundled
comments, a modern web application, deliberately non-storable responses and
cacheable content. They remain in the report; no rule was changed to IGNORE.
A passive unauthenticated HTTP scan does not establish absence of vulnerabilities.
The scanner was ZAP 2.17.0, image digest
`ghcr.io/zaproxy/zaproxy@sha256:781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef`.

The final application suite explicitly omitted ZAP; the separate final scan above
records its actual completion. Each archive includes its own tested base revision,
source fingerprint and original/published file hashes. Both use base revision
`c0c126f13d61f75e6564b91da5f73eabfd68a703` plus the recorded working changes.
The only later QA code change expanded the report export allowlist and passed
five targeted checks. Runtime application code was unchanged after the final suite; vendored font
license line endings were normalized during final patch validation.
A disk-full attempt before these runs failed and is not counted as passing.

[Actual hosted reports and artifact links](qa-evidence/README.md) are available
from an executed Actions run. That earlier hosted run retained passing Selenium
and backend reports but failed its ZAP setup; it is not represented as green.
Tracked archives and 90-day future artifact retention address report expiry.
The security follow-up branch includes these archives for pull request review.

[EC2 HTTPS commands](EC2_HTTPS.md) are prepared for the operator to run inside the
instance. Production HTTPS, SSH restriction and encrypted-volume migration remain
pending; no production infrastructure was changed. The supplied AWS output shows
world-open SSH and an unencrypted EBS root volume, alongside required IMDSv2.

Validation used `/Users/dev/Library/Caches/agentic-security-review` because the IDE
checkout contains unreadable iCloud-offloaded files. Complete source changes and
reports are preserved there; unreadable existing IDE files were not overwritten.
