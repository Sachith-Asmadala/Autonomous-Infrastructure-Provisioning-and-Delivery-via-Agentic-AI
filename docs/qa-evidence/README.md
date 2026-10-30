# Actual QA evidence

[Hosted GitHub Actions run 40998730226](https://github.com/Malithi2001/Autonomous-Infrastructure-Provisioning-and-Delivery-via-Agentic-AI/actions/runs/40998730226)
ran the committed revision `c0c126f13d61f75e6564b91da5f73eabfd68a703`.
It uploaded backend artifact `12951559538` and browser/security artifact
`12952094149`. GitHub artifact downloads require a signed-in account with read
access; the selected sanitized archives below are retained in repository source
for review after Actions artifacts expire.

The hosted backend/harness checks passed 378 cases; Selenium/security passed
64 cases (52 browser and 12 controlled security). The overall hosted run failed
because its then-current ZAP rule file used spaces instead of required tabs.
That setup failure is preserved, not represented as a completed scan.

- [Actual hosted Selenium HTML/XML and traceability archive](hosted-40998730226/20261030T034503Z-01978c.zip)
- [Hosted browser archive checksums and provenance](hosted-40998730226/20261030T034503Z-01978c.json)
- [Actual hosted backend XML and traceability archive](hosted-40998730226/20261030T034236Z-facd3e.zip)
- [Hosted backend archive checksums and provenance](hosted-40998730226/20261030T034236Z-facd3e.json)

Archives contain actual generated files. `PROVENANCE.json` records original and
published SHA-256 values, tested revision/source fingerprint and observed stage
statuses. Redaction removes local user paths and recognizable token formats;
test outcomes are preserved. No screenshots or passing results were fabricated.

Current workflow changes retain future Actions artifacts for 90 days and include
checksummed evidence exports. See [GitHub artifact access documentation](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts).

## Completed isolated security follow-up

- [Final application Selenium HTML/XML, traceability and supplemental evidence](security-followup/20261030T044046Z-203962.zip): 454 passing cases; ZAP recorded separately.
- [Final completed ZAP HTML/JSON/findings](security-followup/20261030T044659Z-368bb5.zip): 0 FAIL, 4 WARN categories, 64 PASS; no High/Medium alerts.
- [Initial completed ZAP baseline](isolated-zap/20261030T035657Z-f8a046.zip): original findings before header remediation.
- [Intermediate scan and genuine browser fixture failure](isolated-zap/20261030T041249Z-85c9ef.zip): preserved as observed.

Each ZIP has a same-name `.json` sidecar with archive SHA-256 and file provenance.
[Security results and remaining findings](../SECURITY_RESULTS.md) explain the
scope and the unverified production HTTPS status. These archives are committed with the security follow-up and are reviewable
from its pull request branch, independently of Actions artifact expiry.
