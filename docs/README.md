# Documentation Index

This directory contains the project documentation for the Smart DevOps Assistant. The docs are written for local development, supervisor demonstrations, and controlled deployments.

## Recommended Reading Order

1. [Project README](../README.md) - project scope, features, setup, modes, and commands.
2. [Startup Guide](../STARTUP_GUIDE.md) - environment files, local startup paths, default admin, and common problems.
3. [Architecture](ARCHITECTURE.md) - frontend, backend, service, agent, data, and GitHub flows.
4. [Agent Design](AGENT_DESIGN.md) - orchestration and specialized agent responsibilities.
5. [API Reference](API_REFERENCE.md) - backend endpoint groups and request/response examples.
6. [Deployment](DEPLOYMENT.md) - local, Docker, hosted, desktop, and security deployment notes.
7. [Audit Logging](AUDIT_LOGGING.md) - execution history, approvals, redaction, and traceability.
8. [GitHub End-to-End Checklist](GITHUB_E2E_CHECKLIST.md) - safe real-repository verification flow.
9. [MVP Demo](MVP_DEMO.md) - short demo script.
10. [Final Demo](FINAL_DEMO.md) - full supervisor presentation flow.
11. [Evaluation Plan](EVALUATION_PLAN.md) - project evaluation approach and metrics.
12. [Mobile App](MOBILE_APP.md) - Capacitor Android build, backend URL setup, APK installation, and troubleshooting.
13. [Security Audit](SECURITY_AUDIT.md) - security-focused review notes.

## Quick Links By Task

| Task | Read |
| --- | --- |
| Run the app locally | [Startup Guide](../STARTUP_GUIDE.md) |
| Explain the project to a supervisor | [Project README](../README.md), [Final Demo](FINAL_DEMO.md) |
| Present the current Admin / Developer demo | [Demonstration Guide PDF](DEMONSTRATION_GUIDE.pdf), [editable print source](DEMONSTRATION_GUIDE.html) |
| Understand backend and frontend architecture | [Architecture](ARCHITECTURE.md) |
| Explain deterministic multi-agent routing | [Agent Design](AGENT_DESIGN.md) |
| Troubleshoot missing workflow failures | [Workflow Failure Guide](WORKFLOW_FAILURES.md) |
| Troubleshoot Create Workflow PR from Repositories | [Workflow PR Guide](PULL_REQUEST_TROUBLESHOOTING.md) |
| Use or test API endpoints | [API Reference](API_REFERENCE.md) |
| Run a real GitHub repository demo | [GitHub E2E Checklist](GITHUB_E2E_CHECKLIST.md) |
| Review approval and audit behavior | [Audit Logging](AUDIT_LOGGING.md) |
| Build the Windows desktop app | [Desktop Guide](../desktop/README.md) |
| Build the Android app | [Mobile App](MOBILE_APP.md) |
| Prepare a final submission ZIP | [Project README](../README.md), `make prepare-submission` |

## Supporting Root Docs

- [AGENTS.md](../AGENTS.md) - rules for future agentic coding work in this repository.
- [Contributing Guide](../CONTRIBUTING.md) - contribution and development expectations.
- [Runtime Verification](../PROJECT_RUNTIME_VERIFICATION.md) - runtime verification notes.
- [Setup Complete](../SETUP_COMPLETE.md) - setup/status snapshot.
- [Hardening Summary](../HARDENING_SUMMARY.md) - security and reliability hardening notes.
- [Demo Implementation Report](../DEMO_IMPLEMENTATION_REPORT.md) - demo implementation summary.

## Main Code Areas

```text
backend/app/agents/       Orchestration and specialized agents
backend/app/api/routes/   FastAPI route modules
backend/app/services/     Business logic services
backend/app/tools/        External integrations
backend/app/ml/           Dataset, model artifacts, training script, reports
frontend/src/pages/       Demo and operator screens
frontend/src/services/    Frontend API client
desktop/                  Electron desktop shell and packaging config
```

## Documentation Rules

- Keep docs aligned with code and Makefile commands.
- Do not document real secrets, tokens, keys, passwords, or private repository data.
- Mark future work clearly instead of describing it as complete.
- Prefer exact endpoint paths, ports, environment variables, and command names.
- Keep AWS, Terraform, Prometheus, and Kubernetes as future work unless explicitly implemented.
- Avoid claiming full production autonomy; this project intentionally uses approval gates and pull requests.
