# Contributing Guide

This project is a final-year DevOps automation system. Changes should keep the MVP stable, explainable, and safe.

## 1. Development Principles

- Keep route handlers thin.
- Put business logic in `backend/app/services/`.
- Put agent logic in `backend/app/agents/`.
- Put low-level integrations in `backend/app/tools/`.
- Reuse existing services before adding new abstractions.
- Do not weaken auth, RBAC, approvals, or webhook signature checks.
- Do not hardcode secrets.
- Do not log tokens, passwords, private keys, or secret-bearing environment variables.
- Keep GitHub repository changes branch-and-PR based.

## 2. Backend Guidelines

Backend layout:

```text
backend/app/api/routes/   FastAPI endpoints
backend/app/agents/       Orchestration and specialized agents
backend/app/services/     Business logic
backend/app/tools/        GitHub, Docker, shell, monitoring integrations
backend/app/models/       SQLAlchemy ORM models
backend/app/schemas/      Pydantic contracts
backend/app/core/         Config, security, database, logging
```

Rules:

- Use async SQLAlchemy sessions for database access.
- Use Pydantic schemas for stable API contracts.
- Use `require_permission(...)` for protected endpoints.
- Use structured logging.
- Keep sensitive data out of logs.
- Add tests when changing behavior.

## 3. Frontend Guidelines

Frontend layout:

```text
frontend/src/pages/       Screens
frontend/src/components/  Reusable UI
frontend/src/services/    API client
frontend/src/store/       Zustand state
frontend/src/types/       Shared TypeScript types
frontend/src/lib/         RBAC/util helpers
```

Rules:

- Use existing layout and UI conventions.
- Handle loading, empty, success, and error states.
- Never expose backend secrets in frontend code.
- Do not store GitHub tokens in browser state.
- Keep RBAC checks in the frontend for UX only; backend permission checks are required.

## 4. Agent Guidelines

- The Orchestration Agent should select one specialized agent for the main task.
- Specialized agents should call services/tools, not duplicate logic.
- Return `AgentResult` from deterministic agents.
- Add approval plans for medium/high-risk actions.
- Do not use LLM-only judgment for risky actions.

## 5. GitHub Safety

Repository modifications must follow:

1. Create branch.
2. Commit intended file.
3. Open pull request.
4. Wait for human review.

Do not:

- push directly to `main` or `master`,
- force push,
- auto-merge,
- delete branches automatically,
- print tokens.

## 6. Documentation

When behavior changes, update:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/AGENT_DESIGN.md](docs/AGENT_DESIGN.md)
- [docs/API_REFERENCE.md](docs/API_REFERENCE.md)

## 7. Quality Checks

Before presenting or merging changes, verify:

- backend tests,
- backend lint/type checks where configured,
- frontend build,
- frontend lint where configured,
- docs do not contain real secrets.

For isolated Selenium, API/security checks, passive ZAP and dissertation evidence,
see [docs/QA_TESTING.md](docs/QA_TESTING.md). Install with `make qa-setup` and
run `make qa`. `make qa-backend` and `make qa-browser` support focused checks.
Generated evidence is under `qa/reports/`; failed, blocked and unexecuted stages
must remain visible in any reported results.
