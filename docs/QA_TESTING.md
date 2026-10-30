# Software quality assurance and evaluation

## Purpose and scope

This framework provides repeatable functional, browser, API, integration,
regression and controlled security tests for the existing DevOps assistant.
It exercises the supervisor demonstration loop while retaining JWT cookies,
database-backed identity checks, role permissions, approval gates and audit logs.
Routine QA never connects to the public EC2 deployment or writes to GitHub.

Test scenarios describe intended coverage. Only generated execution reports
establish observed outcomes. A collected, skipped or blocked case is not a pass.

## Environment and isolation

Use Python 3.11, Node.js 22 (including the existing Capacitor toolchain), and
installed Chrome or Chromium. Selenium Manager supplies the matching driver;
its first run needs network access. Docker Engine is required only for ZAP.
The Linux GitHub Actions runner supports the scanner's host network connection.
Docker Desktop requires host networking enabled for the same command on macOS.

`python -m qa.run` creates an empty temporary working directory, a random
loopback port, a fresh SQLite database and random test credentials. Environment
variables containing production connections and external credentials are not
inherited. The backend does not read the repository's `.env` from its temporary
working directory. Auth bypass is disabled and HITL remains enabled.

The QA-only server validates the disposable database path and marker before
importing the application. Its control endpoints require a per-run secret.
The frontend is built into that temporary directory and served on the same
origin as FastAPI. Readiness checks verify the run identifier, backend health
and React HTML before testing. The runner stops its server and removes the
temporary database on completion, including test failures.

| Boundary | Behavior during QA |
|---|---|
| Login, registration, logout and RBAC | Real routes, cookies and isolated database users |
| Workflow generation and repository readiness | Real analysis and generator services |
| Failure classification | Existing committed joblib classifier, loaded lazily |
| Orchestration | Real deterministic router and specialist agents |
| Chat provider | Fixed response; explicit controlled error and delay fixtures |
| GitHub repository input | `qa/demo` fixture tree; controlled auth failure fixture |
| Repository writes, shell and deployments | External execution disabled |
| Docker | Deterministic read fixtures; host Docker socket is not exposed to app |
| Approval and execution records | Real database-backed routes; isolated seed records |
| Evaluation metrics | Historical stored metrics, not a new accuracy experiment |

No live LLM tests are enabled by this runner. Tests marked `real_llm` are excluded.
Any separate live-provider evaluation requires an explicitly configured test
environment and should report its cost, model/version and nondeterminism separately.

## Installation and local execution

From the repository root:

```bash
make qa-setup
make qa-backend
make qa-browser
make qa-security
# Full backend, QA harness, Selenium, controlled security and passive baseline:
make qa
```

`qa-setup` uses the established `make setup` dependency flow, then installs the
QA-only dependencies in `qa/requirements.txt`. It creates example `.env` files
only when missing, as the existing setup command already does.

`make qa-browser` deliberately excludes ZAP and records it as **Not Executed**.
For browser plus controlled security plus ZAP in one isolated session:

```bash
backend/venv/bin/python -m qa.run --suite ui-security
```

Optional variables:

```bash
# Set only when Chrome/Chromium is not discoverable automatically:
export QA_CHROME_BINARY=/path/to/chrome
# Optional dedicated QA account password; otherwise generated for each run:
# export QA_TEST_PASSWORD=<temporary-test-value>
```

Never supply real administrator credentials. Do not pass a production URL:
the runner owns the test server and accepts no external application target.
ZAP additionally rejects non-loopback targets. The runner supports macOS/Linux;
use Linux/WSL for Windows CI-style execution. On macOS, the scanner container
uses Docker Desktop's `host.docker.internal` gateway to that same isolated
loopback application; it never accepts a public target. ZAP rule entries use
tab separators, as required by its packaged baseline script.

| Runner exit code | Meaning |
|---|---|
| 0 | Requested stages passed; deliberately excluded stages remain explicitly identified |
| 1 | Test assertion/build failure or ZAP FAIL finding |
| 2 | Setup/collection/environment blocker; inspect stage reports |
| 3 | Passive ZAP warning(s), with no failed or blocked stage |

The original ZAP exit code remains in `summary.json`: 0 success, 1 FAIL,
2 WARN, 3 scanner/setup failure. Warnings are not suppressed or silently converted
to passing security evidence. A missing JSON scan report is a blocker.

The Actions step handles **runner** exit 3 with a visible GitHub warning annotation
and a successful step. It preserves `Warning` in the actual reports and summary;
success means the configured failure gate passed, not that the scan found nothing.
Runner exit 1 (test/build/ZAP FAIL), exit 2 (blocked/setup), and every other nonzero
exit still fail the step. In particular, ZAP's own exit 3 is a scanner setup failure
mapped to runner exit 2; it is never accepted by this warning handling.

## Selenium architecture and scenario coverage

`qa/e2e/conftest.py` owns reusable Chrome, isolated-service, account and fault
fixtures. Each test receives a fresh headless browser. Page objects live in
`qa/e2e/pages/base.py`: `Page`, `LoginPage`, `WorkspacePage`, `ChatPage`,
`OrchestrationPage`, `CICDPage`, `RepositoryPage`, `FailuresPage`, `ApprovalsPage`,
`AuditPage`, `EvaluationPage` and `SettingsPage`.

Page objects use explicit waits, accessible names and existing form IDs.
Navigation waits for DOM readiness; page objects then wait for application content,
so third-party fonts/images do not control the browser's full-page load deadline.
Navigation waits tolerate transient React element replacement. Tests use no
arbitrary browser sleeps. Controlled provider delay tests verify completion and
duplicate-submission prevention without invoking an LLM.

| Module | Scenario IDs | Main checks |
|---|---|---|
| Authentication | AUTH-01–09 | Required fields, invalid login, real temporary login/registration, confirmation, logout, protected URLs, admin restriction |
| Dashboard | DASH-01–03 | Cards/activity, sidebar destinations, refresh, partial backend failure |
| Agent chat | CHAT-01–05 | Authorized submit, deterministic response, whitespace guard, provider/HTTP failure and recovery, delay |
| Orchestration | ORCH-01–03 | Four real specialist routes, JSON context validation, unsupported request, result and trace |
| CI/CD assistant | CICD-01–03 | Known classifier fixture, fix visibility, empty inputs, generated YAML parsed into jobs |
| Repositories | REPO-01–04 | Fixture analysis, stack, readiness/findings, invalid identifier, GitHub auth error, PR approval gate |
| Workflow failures | FAIL-01–03 | Saved category/confidence, expandable log/fix, matching/nonmatching search, empty and error states |
| Approvals | HITL-01–03 | Owned pending controls, expired/privileged restrictions, reviewer rejection, live expiry |
| Audit | AUDIT-01–03 | Owned success/failure records, status filter, admin actor search, sensitive-field checks |
| Evaluation/settings | EVAL-01–02, SET-01–02 | Historical metrics formatting, role restriction, connection status, invalid URL and backend errors |

Parameterized instances receive distinct ID suffixes. A test may contain several
related assertions; passing a case does not establish coverage of every possible
input. Backend API tests separately verify that hiding a UI control cannot bypass
authorization.

## Backend and integration tests

The existing `backend/tests` suite is retained. It already covers cookies,
token/session invalidation, two-role access, account management, ownership,
repository analysis, workflow generation, all agents, GitHub tools, audit filters,
failure diagnosis, webhook persistence and approval execution. New boundary tests
in `test_qa_regressions.py` cover the five requested source-review findings.

Existing database fixtures use memory or disposable SQLite files. The runner also
sets a safe process-wide database URL before importing tests. No external secrets
are supplied. Coverage and test reports are written outside the disposable working
directory. The suite uses synthetic fixtures rather than private/customer logs.

`qa/security/test_controlled_security.py` supplements these tests through the
running HTTP application. It verifies anonymous rejection, developer restrictions,
cookie flags/logout, denied cross-origin preflight, approval ownership/rejection
and replay, expired execution rejection, and safe account/audit response fields.
It also records the actual header inventory. That inventory test establishes that
observations were collected; it does **not** assert that every protection exists.

`qa/tests/test_runner.py` verifies isolation, scanner target restrictions, ZAP exit
classification, evidence redaction, report truthfulness and deployment-free CI.

## Passive security evaluation

`qa/zap/scan.py` runs only `zap-baseline.py`: a time-limited spider followed by
passive analysis. No active scan, authentication context, brute force or public
target is configured. `qa/zap/baseline.conf` retains warnings and makes a missing
HttpOnly flag a failure. It contains no ignored findings.

Reports include `zap.html`, `zap.json`, `zap.md`, `zap.log` and normalized
`security-findings.json` when the scanner executes. The normalized record retains
finding, endpoint, risk, evidence, remediation and false-positive review fields.
No remediation is marked verified automatically.

Security evaluation has deliberate limits: an unauthenticated spider does not
exercise logged-in SPA interactions; pytest covers those authorization paths.
The loopback HTTP server does not represent production TLS, Nginx, HSTS or mixed
content behavior. Existing cookie tests cover explicit Secure settings for HTTP
and HTTPS clients. Local HTTP cookies without Secure must not be interpreted as
verification of production HTTPS configuration.

## Confirmed defects and focused corrections

| Finding | Evidence before correction | Correction and regression evidence |
|---|---|---|
| Readiness exaggerates file-name evidence | `.env.example` and unrelated environment documentation could trigger a critical exposure claim | Exclude conventional template suffixes; inspect exact suspicious basenames; warn that contents need review. Existing expectation updated to evidence-based severity. |
| Expired approvals still advertise decisions | Backend response flags depended on `pending` status alone; UI offered decisions and described expiry ambiguously | Expiry gates response flags; frontend blocks stale actions, updates every second, labels expiry, and reads timezone-free API timestamps as UTC. Backend execution gate remains enforced. |
| Confidence accepts invalid numbers | NaN, infinity and probabilities outside [0,1] could be returned | Return unavailable confidence for invalid values; preserve genuine low confidence; reject non-text service inputs; cover missing/corrupt artifacts and cached loading. |
| Shell prefix bypass and disclosure | Extra flags/paths were admitted by prefix matching; blocked responses and output could echo credentials | Validate complete argument vectors, bound journal counts, restrict service identifiers, disable pagers, reject operators/malformed input, and redact supported secret patterns in logs/results. No shell interpreter is invoked. |
| Malformed signed webhook errors | Invalid JSON/non-object nested payloads could raise unhandled errors before event dispatch | Return clean HTTP 400 after signature verification; preserve invalid-signature rejection and safe unsupported-event acknowledgement. |

The initial new-regression experiment produced **37 failures and 8 passes**.
The focused retest then produced **48 passes**, including the three existing
readiness tests. Additional edge regressions were added after that experiment;
use the final generated report for their current totals.

Environment issue: several local files were macOS cloud placeholders and initially
returned empty reads. The classifier first raised `EOFError`; restoring the exact
unchanged local Git bytes resolved loading without retraining or changing model
artifacts. This is an environment correction, not a classifier accuracy result.
An exploratory browser run was interrupted after identifying harness expectation
mismatches and this environment issue; it must not be used as the final pass count.

## Evidence and actual results

Every invocation writes `qa/reports/<UTC-run-id>/`; `qa/reports/latest` points to
the newest invocation. Evidence is intentionally Git-ignored. Preserve the entire
run directory when submitting dissertation appendices or CI artifacts. Selected
sanitized HTML/XML/traceability and real ZAP reports are preserved as checksummed
archives in [qa-evidence](qa-evidence/README.md), together with a hosted Actions
run link. Export an actual run with:

```bash
backend/venv/bin/python -m qa.export_evidence qa/reports/latest qa/published
```

| Artifact | Content |
|---|---|
| `manifest.json` | Actual UTC timestamp, commit, dirty-worktree flag, source fingerprint, file identities, Python/platform |
| `summary.json`, `summary.md` | Observed stage statuses and totals, including blockers |
| `traceability.md`, `*-cases.json` | Unique test ID, module, scenario, expected/actual, status, evidence, date and commit |
| `backend.html`, `backend.xml`, `backend.log` | Backend HTML, JUnit and console evidence |
| `coverage.xml`, `coverage/index.html` | Statement coverage, including missing lines |
| `selenium.html`, `selenium.xml`, `selenium.log` | Browser execution evidence |
| `screenshots/*.png` | Automatically captured genuine failure screenshots; none fabricated for passing tests |
| `security.html`, `security.xml`, `header-observations.json` | Controlled auth/security results and actual response-header observations |
| `zap*`, `security-findings.json` | Passive scan evidence, only when executed |

The manifest combines Git object identities for unchanged tracked files with
SHA-256 hashes for changed/new files. The source fingerprint distinguishes tested
uncommitted changes from the base commit. Do not cite the base SHA alone as though
the working tree were clean. Generated artifacts and environment files are excluded.

Screenshots hide form fields before capture. Text reports remove the run's
temporary credentials and recognizable token patterns. Logs do not intentionally
collect cookie stores or auth headers. Review artifacts before public distribution;
pattern-based redaction cannot identify every possible secret representation.

Final local outcomes and known limitations are recorded in
[QA_RESULTS.md](QA_RESULTS.md). That file separates executed checks, historical
ML metrics, completed passive scans and any blocked checks.

## CI and reproducibility limitations

`.github/workflows/quality-assurance.yml` is independent of the existing CI,
packages, release and deployment workflows. It runs on pull requests to `main`
or manual dispatch, with read-only repository permissions and no production
secrets. Backend tests precede the browser/security job, which still runs to
collect evidence if backend checks fail. Upload steps run regardless of outcome.
The QA runner performs service startup, health checks and final cleanup.

Actual hosted run outcomes and artifact links are recorded in
[qa-evidence](qa-evidence/README.md). Uploads retain the original reports and
sanitized checksummed exports for 90 days, including failing runs. Repository
archives provide selected evidence after artifact expiry. A hosted setup failure
is recorded separately from completed local scans; it is never a passing scan.

Top-level dependencies are pinned, but the backend's existing transitive ranges,
installed Chrome and ZAP stable image can change. Preserve `manifest.json`, test
logs, browser capabilities and scanner image information for each experiment.
SQLite coverage does not substitute for separate PostgreSQL concurrency/load
testing. This framework does not establish performance SLOs, all-browser support,
live GitHub reliability or absence of vulnerabilities.

Implementation references: [Selenium explicit waits](https://www.selenium.dev/documentation/webdriver/waits/),
[Selenium Manager](https://www.selenium.dev/documentation/selenium_manager/), and
[ZAP baseline behavior and exit codes](https://www.zaproxy.org/docs/docker/baseline-scan/).
