# QA execution results

**Current follow-up:** [completed ZAP scans, 454-test security retest, hosted
artifacts and EC2 HTTPS status](SECURITY_RESULTS.md). The execution below is the
initial historical run; its blocked scanner status was subsequently resolved.

This document records observed local execution separately from the scenario plan
in [QA_TESTING.md](QA_TESTING.md). Reports are the primary evidence; no blocked
scenario is represented as passing.

Historical model metrics are stored under `backend/app/ml/reports/` and were
generated on 2 June 2026. They are not newly measured by UI rendering tests.

## Initial execution: 30 October 2026

The final run began at **04:58:31 Asia/Colombo**, equivalent to
**29 October 2026, 23:28:31 UTC**. Its identifier is
`20261029T232831Z-4f4066`. The application base revision was
`6bd36969350b28121a73005dff3d7d935c66a50a`, with uncommitted QA and correction
changes. The exact tested source fingerprint is
`84deff1025154dbb2af327fbae6785cb528b6b34001a165cfbad21b8f2ad2952`.
The per-file identities are preserved in
[manifest.json](../qa/reports/20261029T232831Z-4f4066/manifest.json).
This results document was populated after execution; it is not a new application
revision or an additional test run.
During reporting the original workspace HEAD advanced to
`76be477027cb81e5b35f7e29aba01b0535737431`. Byte-level verification confirmed
that all 40 changed/new files matched the tested snapshot except this results
document, which was populated afterwards. See
[source-verification.json](../qa/reports/20261029T232831Z-4f4066/source-verification.json).

| Check | Actual outcome | Evidence |
|---|---|---|
| Existing and extended backend tests | 365 passed; one dependency warning | [Backend HTML](../qa/reports/20261029T232831Z-4f4066/backend.html) |
| Selenium, all ten modules | 52 passed, no automatic retries | [Selenium HTML](../qa/reports/20261029T232831Z-4f4066/selenium.html) |
| Controlled HTTP security checks | 12 passed | [Security HTML](../qa/reports/20261029T232831Z-4f4066/security.html) |
| QA harness safety/report checks | 13 passed | [Harness HTML](../qa/reports/20261029T232831Z-4f4066/qa-tools.html) |
| Backend statement coverage | 3,515 / 4,869 statements: 72.19% | [Coverage](../qa/reports/20261029T232831Z-4f4066/coverage/index.html) |
| Frontend production build/type checking | Passed | [Build log](../qa/reports/20261029T232831Z-4f4066/frontend-build.log) |
| Python lint, backend typing, frontend lint | Passed; typing checked 61 source files | [Supplemental checks](../qa/reports/20261029T232831Z-4f4066/supplemental-checks.json) |
| Existing Python workflow/deployment regressions | 23 passed | [Python results](../qa/reports/20261029T232831Z-4f4066/workflow-python.log) |
| Existing JavaScript workflow/API regressions | 20 passed | [JavaScript results](../qa/reports/20261029T232831Z-4f4066/workflow-javascript.log) |
| OWASP ZAP Baseline | **Blocked / Not Executed**: Docker daemon unavailable | [QA summary](../qa/reports/20261029T232831Z-4f4066/summary.md) |
| Supplemental npm dependency audit | **Warning**: 18 advisories, exit 1 | [Audit JSON](../qa/reports/20261029T232831Z-4f4066/npm-audit.json) |

The framework executed **442 passing pytest cases**. The additional 43 existing
workflow checks are reported separately. The overall QA command returned **2**
because ZAP could not execute. This is not a fully passing security assessment.

The [traceability table](../qa/reports/20261029T232831Z-4f4066/traceability.md)
contains each case's ID, module, scenario, expected/actual result, status, date,
revision and evidence reference. JUnit XML accompanies each HTML report. There
are no final-run failure screenshots because no browser case failed; screenshots
from exploratory failures remain with their original runs.

## Test environment and reproducibility

Execution used Python 3.11.15, Node.js 20.20.2 for the web build, macOS, SQLite,
and headless Chrome. The exact browser/driver versions are recorded in
[browser.json](../qa/reports/20261029T232831Z-4f4066/browser.json); Python package
versions are in the manifest. CI is configured for Python 3.11 and Node.js 22,
which also meets the existing Capacitor CLI requirement. No hosted Actions run
was triggered during this task.

The Desktop repository was offloading files through macOS cloud storage,
including installed dependencies. Early attempts encountered empty model reads
and stalled imports. Final validation therefore used an equivalent local Git
worktree at `/Users/dev/Library/Caches/agentic-qa-workspace`, with all changed/new
source copied after checking its byte length. Dependencies were installed using
`make backend-install` with an external `BACKEND_VENV`, `make frontend-install`,
and the QA requirements file. The interpreter was
`/Users/dev/Library/Caches/agentic-qa-venv/bin/python`.

The final command in that worktree was:

```bash
/Users/dev/Library/Caches/agentic-qa-venv/bin/python -m qa.run
```

Evidence was copied back to the original repository without replacing the
application source or test results. Normal reproduction commands are in
[QA_TESTING.md](QA_TESTING.md). For this machine, use a fully downloaded local
checkout outside cloud-synced folders.

To unblock the scan, start Docker Engine (on this Mac, `open -a Docker`), wait
for `docker info` to succeed, enable Docker Desktop host networking or use the
Linux Actions runner, then run:

```bash
make qa-security
```

No ZAP HTML/JSON vulnerability report was generated, and no scanner finding or
security pass is inferred from its absence. The GitHub Actions workflow is
implemented and locally inspected, but remains **Not Executed on GitHub**.

## Earlier experiments retained for audit

| Experiment | Observed outcome | Interpretation |
|---|---|---|
| Initial five-finding regression cases | 37 failed, 8 passed | Confirmed defects before focused corrections; [console log](../qa/reports/20261029T232831Z-4f4066/exploratory-regressions-before.log) |
| Focused correction retest | 48 passed | Included the three existing readiness tests; [console log](../qa/reports/20261029T232831Z-4f4066/exploratory-regressions-after.log) |
| `20261029T231352Z-01e6a9` | 441 passed, one UI assertion failed | GitHub fixture bypassed real repository-name validation; fixture and expectation corrected. [Summary](../qa/reports/20261029T231352Z-01e6a9/summary.md) |
| `20261029T232008Z-63c479` | 441 passed, one UI setup blocked | Chrome renderer timed out before settings assertions. [Summary](../qa/reports/20261029T232008Z-63c479/summary.md) |
| Final `20261029T232831Z-4f4066` | 442 passed; ZAP blocked | DOM-ready navigation plus explicit application waits verified in a complete fresh run. |

Earlier interrupted setup/browser probes are also retained under `qa/reports/`.
Their partial counts must not be combined with final counts. No automatic test
retry plugin or failure-status suppression was added.

## Security observations and unresolved issues

These observations are distinct from the five corrected source defects described
in the [implementation guide](QA_TESTING.md#confirmed-defects-and-focused-corrections).
Risk labels below are contextual review priorities, not measured exploitability.

| Observation | Endpoint / scope | Risk | Evidence and remediation | False-positive/context considerations | Status |
|---|---|---|---|---|---|
| CSP and framing protection absent | `/`, `/api/v1/health`, `/api/v1/auth/me`, `/api/v1/audit` | Medium | Actual header absent; define compatible CSP and framing policy. [Inventory](../qa/reports/20261029T232831Z-4f4066/header-observations.json) | QA serves the bundle directly; production Nginx/TLS was not evaluated. CSP frame-ancestors can replace X-Frame-Options. | Unresolved; no remediation claimed |
| `X-Content-Type-Options` absent | Same four observed endpoints | Low | Actual header absent; set and verify `nosniff`. Same inventory. | Reverse-proxy behavior is outside this run. | Unresolved |
| Cache policy absent | Same four endpoints, including authenticated `/auth/me` and `/audit` | Medium for private responses | Actual `Cache-Control` absent; evaluate `no-store` for private/auth responses and route-specific public caching. Same inventory. | Header absence alone does not demonstrate a cache leak. | Unresolved |
| Public health response includes absolute model path | Anonymous `/api/v1/health/status` | Low | Observed `ml_model.path`; return a logical name or restrict detailed diagnostic paths. [Observation](../qa/reports/20261029T232831Z-4f4066/health-observation.json) | Demo diagnostics intentionally show integration state; no file contents were disclosed. | Unresolved |
| Dependency advisories | Existing frontend dependency tree | 2 critical, 11 high, 5 moderate | `npm audit --json` reported 18 advisories; critical entries included `@capacitor/android` and `tar`. Review advisory paths and compatible upgrades. [Audit](../qa/reports/20261029T232831Z-4f4066/npm-audit.json) | Development/native tooling exposure differs from deployed web-runtime exposure; reachability was not established. | No upgrades or remediation verification |
| TLS, HSTS and mixed content | Public deployment | Not assessed | Requires an authorized isolated HTTPS deployment and separate evaluation. | Loopback HTTP and unauthenticated passive scanning cannot establish production TLS posture. | Not Executed |

The controlled cookie, CORS, authorization and approval tests passed, but these
observations prevent a claim that the application is vulnerability-free. The
16 header observations and the separate health-path observation preserve endpoint,
evidence, remediation and review context. They are pytest/manual HTTP observations,
not fabricated ZAP results.

## File inventory

Created:

- `qa/run.py`, `server.py`, `reporting.py`, `pytest.ini`, `requirements.txt` and package initializers.
- `qa/e2e/conftest.py`, `pages/base.py` and ten module test files.
- `qa/security/conftest.py`, `test_controlled_security.py` and `qa/tests/test_runner.py`.
- `qa/zap/scan.py` and `baseline.conf`.
- `backend/tests/test_qa_regressions.py` and `.github/workflows/quality-assurance.yml`.
- `docs/QA_TESTING.md`, this results summary, and generated Git-ignored evidence.

Modified:

- Backend webhook validation, approval response policy, readiness assessment,
  confidence/input validation and shell validation/redaction.
- `frontend/src/pages/ApprovalsPage.tsx` for expiry presentation, UTC timestamps
  and stale decision guards.
- The existing readiness regression expectation, `Makefile`, `CONTRIBUTING.md`
  and `.gitignore`.

Existing CI/deployment workflows, ML artifacts and infrastructure configuration
were preserved. No GitHub modification, PR, deployment or production-database
operation was performed.

## Chapter 6 adaptation

The software quality evaluation used a layered strategy combining existing pytest
unit and integration tests, Selenium browser automation and controlled HTTP
security checks. External language-model, GitHub and Docker operations were
replaced with deterministic fixtures, while authentication, authorization,
orchestration, database persistence and approval enforcement used application
code. This design increased repeatability and prevented unintended changes to
production repositories or infrastructure.

Source inspection and boundary-case experiments identified defects in repository
readiness classification, expired approval presentation, prediction confidence
validation, shell argument restrictions and webhook payload handling. Focused
corrections were evaluated through regression tests. Evidence includes JUnit and
HTML reports, statement coverage, failure screenshots and a traceability table
linking each executed scenario to its observed result and tested source revision.

In the final execution, all 442 framework test cases passed: 365 backend cases,
52 Selenium cases, 12 controlled HTTP security cases and 13 QA harness cases.
Backend statement coverage was 72.19%, with 3,515 of 4,869 statements exercised.
An additional 43 existing workflow regression checks passed. Earlier experiments
and the Chrome setup timeout were retained separately instead of being discarded
or silently retried. The ZAP baseline could not execute because the Docker daemon
was unavailable, so this component of the security evaluation remains blocked.

Controlled observations identified missing response headers, public diagnostic
path disclosure and 18 dependency advisories requiring further review. Therefore,
the passing functional and authorization checks should not be interpreted as proof
of complete security. The existing model artifact reports a dataset of 330 examples,
11 classes, accuracy of 79.52% and macro F1 of 77.60%, generated on 2 June 2026.
Those values belong to a historical model experiment; this QA run verified fixture
prediction, failure handling, confidence formatting and metric presentation rather
than conducting a new independent accuracy or calibration study.

The findings support the repeatability of the tested demonstration workflows and
the effectiveness of the corrected validation and approval controls under the
specified conditions. Generalization remains limited by deterministic external
service fixtures, SQLite-based integration testing, a single browser family,
incomplete statement coverage and the absence of a completed passive scan or
production HTTPS evaluation.
