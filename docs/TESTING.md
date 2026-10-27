# Backend test isolation

Run `make test-backend` for the full backend suite and `make lint` for the
backend/frontend checks. `make build` builds the frontend production bundle.

HTTP and WebSocket integration tests must not depend on a previously initialized
application database. `tests/conftest.py` provides `isolated_app_database` for
tests that use the real application session factory. It creates all ORM tables
in a temporary SQLite file and supplies the same session factory to application
startup, HTTP dependencies, and agent WebSocket handlers. Connections use
`NullPool` because separate TestClient contexts run separate event loops.

The CI/CD, application integration, and streaming test modules explicitly use
this fixture. Existing tests that override `get_db` keep their own database
fixtures. Auth and RBAC remain enabled; isolated fixtures do not bypass account
validation or approval checks. Test LLM responses and fixture credentials keep
these tests independent of a local `.env` or hosted LLM credentials.

The GitHub Actions backend test job selects the test LLM provider and does not
inject live LLM/GitHub credentials. Streaming assertions fail immediately when
an unexpected error/control frame arrives, rather than waiting for heartbeat
frames. The job has a ten-minute timeout to bound unexpected hangs.

CI coverage uses `pytest tests/ -v --tb=short --cov=app --cov-report=xml
--cov-report=term-missing`. Database setup belongs in the fixtures; no manual
initialization command is required before the test run.
