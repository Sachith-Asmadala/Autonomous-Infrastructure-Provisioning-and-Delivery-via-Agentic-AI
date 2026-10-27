# Final Demo Guide

This guide gives a clean supervisor demo flow. It focuses on the working MVP: CI/CD setup, failure diagnosis, pull requests, approval, and audit.

## 1. Demo Story

Recommended opening:

> This project is a Smart DevOps Assistant that automates repetitive CI/CD setup and failure diagnosis while keeping repository changes safe through pull requests, human approval, and audit logging.

The demo should prove:

- the user can authenticate,
- the assistant can analyze logs,
- the assistant can inspect a GitHub repository,
- the assistant can generate a workflow,
- the assistant can create a workflow PR,
- failed GitHub Actions can be diagnosed,
- risky actions can be approved or rejected,
- the audit trail records what happened.

## 2. Demo Roles

Use an admin account for the full demo.

Explain role behavior:

- developer: diagnosis and lower-risk development operations,
- admin: full platform owner.

## 3. Suggested Demo Sequence

### Step 1 - Login

Show:

- login page,
- successful session,
- protected navigation.

Explain:

> The backend uses JWT authentication, httpOnly cookies, refresh sessions, and role-based access control.

### Step 2 - Multi-Agent Overview

Open the multi-agent page.

Try a low-risk request such as repository scan or log diagnosis.

Explain:

> The Orchestration Agent detects intent and selects exactly one specialized agent: CI/CD, Diagnosis, GitHub, or optional CLI inspection.

### Step 3 - Pasted CI/CD Failure Diagnosis

Open the diagnosis page and paste a known CI/CD failure log.

Expected output:

- predicted label,
- confidence,
- suggested fix,
- recommendation.

Explain:

> The model is a TF-IDF plus Logistic Regression classifier trained on CI/CD failure examples. It gives a failure category and a practical fix suggestion.

### Step 4 - Repository Scan

Open repository setup and scan a repository.

Show:

- detected language,
- framework,
- package manager,
- project directory,
- existing workflow detection,
- warnings,
- readiness score,
- recommended next actions.

Explain:

> The repository analyzer checks file paths and selected manifest contents, so it can identify package managers, test presence, monorepo folders, and existing CI workflows.

### Step 5 - Workflow PR Creation

Create a generated CI workflow pull request.

Show:

- branch name,
- workflow path,
- PR URL,
- PR body.

Explain:

> The system never pushes directly to main or master. It creates a branch, commits the workflow file, and opens a pull request for review.

### Step 6 - Failed Workflow Diagnosis

Use a failed GitHub Actions run or stored sample.

Show:

- Workflow Failures page,
- repository,
- workflow run ID,
- predicted label,
- confidence,
- suggested fix.

Explain:

> GitHub webhooks can trigger diagnosis automatically. When possible, the backend downloads the real Actions logs before running the ML prediction.

### Step 7 - Fix PR Or Approval

For a supported failure, request a fix PR.

Show either:

- a created PR, or
- an approval request.

Explain:

> The system only applies selected safe fixes. Higher-risk changes wait for a human approval decision.

### Step 8 - Approval Queue

Open the approvals page.

Show:

- pending action,
- tool name,
- summary,
- risk level,
- approve/reject decision.

Explain:

> Human-in-the-loop control prevents risky automation from silently changing repositories or infrastructure.

### Step 9 - Execution/Audit History

Open executions page.

Show:

- source,
- status,
- tool name,
- actor,
- timestamps,
- details.

Explain:

> Every important automation action becomes an execution record. This makes the system auditable for supervisors and operators.

## 4. Architecture Talking Points

Use this short explanation:

> The frontend sends requests to FastAPI. FastAPI enforces auth and RBAC, then calls either route services or the Orchestration Agent. The Orchestration Agent selects one specialized agent. Services handle repository analysis, workflow generation, GitHub App tokens, ML prediction, approvals, and audit logging. Repository changes always go through pull requests.

## 5. Safety Talking Points

Important points to mention:

- no hardcoded secrets,
- no direct push to main/master,
- webhook signature verification when configured,
- role-protected endpoints,
- human approval for risky actions,
- audit trail,
- secret redaction in logs.

## 6. If Something Fails During Demo

Common causes:

- GitHub token/App lacks contents or pull request permissions.
- GitHub webhook URL is not public.
- Repository already has the generated workflow file and overwrite was not selected.
- Dependency graph is disabled for GitHub dependency review actions.
- Model artifacts are missing.
- User role does not have `executions:write`.

Demo-safe fallback:

- show pasted log diagnosis,
- show repository scan/readiness,
- show generated YAML,
- show stored execution/audit records,
- explain the blocked GitHub permission as expected safety behavior.

## 7. Recommended Closing

> The project demonstrates a safe agentic DevOps loop: detect, recommend, generate, propose through PR, require approval when needed, and record everything for audit. It is not replacing DevOps engineers; it reduces repetitive work while keeping humans in control.

## Screenshot Evidence

Before the final report submission, capture the required UI, GitHub, audit, evaluation, and model evidence listed in `docs/screenshots/README.md`.

Keep screenshots in `docs/screenshots/` for report preparation only. Do not include secrets, tokens, private keys, or sensitive environment values in screenshots.
