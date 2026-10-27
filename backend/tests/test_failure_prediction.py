"""Tests for the CI/CD failure prediction service and API route."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes import auth, model
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.core.security import UserRole, hash_password
from app.models.models import Execution, User
from app.services import failure_prediction_service as service


TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = async_sessionmaker(test_engine, expire_on_commit=False)


def _build_test_app() -> FastAPI:
    test_app = FastAPI(title="Failure Prediction Test App")
    test_app.include_router(auth.router, prefix="/api/v1/auth")
    test_app.include_router(model.router, prefix="/api/v1/model")
    return test_app


app = _build_test_app()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture()
async def db_session() -> AsyncSession:
    async with TestSession() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(autouse=True)
async def override_db(db_session: AsyncSession):
    result = await db_session.execute(select(User).where(User.email == "member@company.example.com"))
    if result.scalar_one_or_none() is None:
        db_session.add(
            User(
                email="member@company.example.com",
                username="member",
                hashed_password=hash_password("member123"),
                role=UserRole.DEVELOPER,
                is_active=True,
            )
        )
        await db_session.commit()

    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    yield
    app.dependency_overrides.pop(get_db, None)


class _FakeModel:
    def predict(self, values):
        assert values[0]
        return ["npm_missing_test_script"]

    def predict_proba(self, values):
        assert values[0]
        return [[0.18, 0.82]]


class _UnknownLabelModel:
    def predict(self, values):
        assert values[0]
        return ["new_unmapped_failure"]

    def predict_proba(self, values):
        assert values[0]
        return [[1.0]]


class _BrokenModel:
    def predict(self, values):
        raise ValueError("internal model stack detail")


def _auth_headers(role: str = "developer") -> dict[str, str]:
    token = create_access_token(
        {
            "sub": str(uuid.uuid4()),
            "username": "model-test-user",
            "role": role,
        }
    )
    return {"Authorization": f"Bearer {token}"}


def test_predict_failure_handles_empty_log(monkeypatch):
    monkeypatch.setattr(service, "_fix_mapping", {"unknown_failure": "Inspect full logs."})

    result = service.predict_failure("   ")

    assert result["label"] == "unknown_failure"
    assert result["confidence"] is None
    assert result["suggested_fix"] == "Inspect full logs."
    assert result["recommendation"]["safe_fix_available"] is False


def test_predict_failure_returns_label_confidence_and_fix(monkeypatch):
    monkeypatch.setattr(service, "_model", _FakeModel())
    monkeypatch.setattr(
        service,
        "_fix_mapping",
        {"npm_missing_test_script": "Add a test script in package.json."},
    )

    result = service.predict_failure("npm ERR! Missing script: test")

    assert result["label"] == "npm_missing_test_script"
    assert result["confidence"] == 0.82
    assert result["suggested_fix"] == "Add a test script in package.json."
    assert result["recommendation"]["risk_level"] == "low"
    assert result["recommendation"]["safe_fix_available"] is True


def test_predict_failure_handles_unknown_label_safely(monkeypatch):
    monkeypatch.setattr(service, "_model", _UnknownLabelModel())
    monkeypatch.setattr(service, "_fix_mapping", {})

    result = service.predict_failure("some new failure pattern")

    assert result["label"] == "new_unmapped_failure"
    assert result["confidence"] == 1.0
    assert result["suggested_fix"] == service.DEFAULT_FIX
    assert result["recommendation"]["safe_fix_available"] is False


def test_predict_failure_reports_missing_model_without_startup_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "_model", None)
    monkeypatch.setattr(service, "MODEL_PATH", tmp_path / "missing-model.joblib")

    with pytest.raises(service.FailurePredictionUnavailable) as exc_info:
        service.predict_failure("npm ERR! Missing script: test")

    assert "Failure prediction model not found" in str(exc_info.value)


def test_predict_failure_wraps_model_runtime_errors(monkeypatch):
    monkeypatch.setattr(service, "_model", _BrokenModel())

    with pytest.raises(service.FailurePredictionError) as exc_info:
        service.predict_failure("npm ERR! Missing script: test")

    assert str(exc_info.value) == "Failure prediction failed. Please try again."


def test_predict_failure_endpoint_requires_auth():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/model/predict-failure",
            json={"log_text": "npm ERR! Missing script: test"},
        )

    assert response.status_code in (401, 403)


def test_predict_failure_endpoint_returns_prediction(monkeypatch):
    monkeypatch.setattr(service, "_model", _FakeModel())
    monkeypatch.setattr(
        service,
        "_fix_mapping",
        {"npm_missing_test_script": "Add a test script in package.json."},
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/model/predict-failure",
            headers=_auth_headers(),
            json={"log_text": "npm ERR! Missing script: test"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["label"] == "npm_missing_test_script"
    assert body["confidence"] == 0.82
    assert body["suggested_fix"] == "Add a test script in package.json."
    assert body["recommendation"]["root_cause"]


@pytest.mark.asyncio
async def test_predict_failure_endpoint_audits_prediction_and_recommendation(monkeypatch, db_session: AsyncSession):
    monkeypatch.setattr(service, "_model", _FakeModel())
    monkeypatch.setattr(
        service,
        "_fix_mapping",
        {"npm_missing_test_script": "Add a test script in package.json."},
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/model/predict-failure",
            headers=_auth_headers(),
            json={"log_text": "npm ERR! Missing script: test"},
        )

    assert response.status_code == 200

    result = await db_session.execute(select(Execution).order_by(Execution.started_at))
    executions = result.scalars().all()
    tool_names = {execution.tool_name for execution in executions}
    assert "failure_prediction_model" in tool_names
    assert "fix_recommendation" in tool_names

    prediction = next(execution for execution in executions if execution.tool_name == "failure_prediction_model")
    assert prediction.status == "completed"
    assert prediction.requested_by == "model-test-user"
    assert "npm_missing_test_script" in (prediction.details or "")


def test_predict_failure_endpoint_returns_clean_unavailable_error(monkeypatch):
    def _raise_unavailable(log_text: str) -> dict:
        raise service.FailurePredictionUnavailable("Failure prediction model not found. Train the model first.")

    monkeypatch.setattr(model, "predict_failure", _raise_unavailable)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/model/predict-failure",
            headers=_auth_headers(),
            json={"log_text": "npm ERR! Missing script: test"},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Failure prediction model not found. Train the model first."}


def test_predict_failure_endpoint_does_not_expose_stack_traces(monkeypatch):
    def _raise_prediction_error(log_text: str) -> dict:
        raise service.FailurePredictionError("internal stack trace with local path")

    monkeypatch.setattr(model, "predict_failure", _raise_prediction_error)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/model/predict-failure",
            headers=_auth_headers(),
            json={"log_text": "npm ERR! Missing script: test"},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "Failure prediction failed. Please try again."}


def test_seeded_developer_can_login_and_predict(monkeypatch):
    monkeypatch.setattr(service, "_model", _FakeModel())
    monkeypatch.setattr(
        service,
        "_fix_mapping",
        {"npm_missing_test_script": "Add a test script in package.json."},
    )

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "devops.engineer@example.com", "password": "developer123"},
        )
        prediction_response = client.post(
            "/api/v1/model/predict-failure",
            json={"log_text": "npm ERR! Missing script: test"},
        )

    assert login_response.status_code == 200
    assert login_response.json()["user"]["email"] == "devops.engineer@example.com"
    assert prediction_response.status_code == 200
    assert prediction_response.json()["label"] == "npm_missing_test_script"


def test_registered_developer_can_predict(monkeypatch):
    monkeypatch.setattr(service, "_model", _FakeModel())
    monkeypatch.setattr(
        service,
        "_fix_mapping",
        {"npm_missing_test_script": "Add a test script in package.json."},
    )

    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "member@company.example.com", "password": "member123"},
        )
        prediction_response = client.post(
            "/api/v1/model/predict-failure",
            json={"log_text": "npm ERR! Missing script: test"},
        )

    assert login_response.status_code == 200
    assert prediction_response.status_code == 200
