"""Prediction service for CI/CD failure log classification."""
from __future__ import annotations

from pathlib import Path
import math
from typing import Any

from app.core.config import settings
from app.core.logging import logger
from app.services.fix_recommendation_service import get_fix_recommendation


ML_DIR = Path(__file__).resolve().parents[1] / "ml"
MODEL_PATH = Path(settings.FAILURE_MODEL_PATH) if settings.FAILURE_MODEL_PATH else ML_DIR / "failure_model.joblib"
FIX_MAPPING_PATH = Path(settings.FIX_MAPPING_PATH) if settings.FIX_MAPPING_PATH else ML_DIR / "fix_mapping.joblib"

UNKNOWN_LABEL = "unknown_failure"
DEFAULT_FIX = "Review the full CI/CD logs to identify the root cause."

_model: Any | None = None
_fix_mapping: dict[str, str] | None = None


class FailurePredictionUnavailable(RuntimeError):
    """Raised when model artifacts or runtime dependencies are unavailable."""


class FailurePredictionError(RuntimeError):
    """Raised when a prediction attempt fails after the model is available."""


def _load_joblib_file(path: Path) -> Any:
    """Import joblib only when an artifact is actually needed."""
    try:
        import joblib
    except ImportError as exc:
        raise FailurePredictionUnavailable(
            "joblib is not installed. Run `pip install -r backend/requirements.txt` "
            "before using failure prediction."
        ) from exc

    return joblib.load(path)


def _get_model() -> Any:
    """Load the trained classifier once and reuse it for later predictions."""
    global _model
    if _model is None:
        if not MODEL_PATH.exists():
            raise FailurePredictionUnavailable(
                "Failure prediction model not found. "
                "Train it with `python3 app/ml/train_failure_model.py` "
                "from the backend directory."
            )
        try:
            _model = _load_joblib_file(MODEL_PATH)
        except FailurePredictionUnavailable:
            raise
        except Exception as exc:
            logger.error(
                "failure_prediction.model_load_failed",
                error_type=exc.__class__.__name__,
                model_path=str(MODEL_PATH),
            )
            raise FailurePredictionUnavailable(
                "Failure prediction model could not be loaded. "
                "Retrain it with `python3 app/ml/train_failure_model.py` from the backend directory."
            ) from exc
    return _model


def _get_fix_mapping() -> dict[str, str]:
    """Load the label-to-remediation mapping once, falling back if absent."""
    global _fix_mapping
    if _fix_mapping is None:
        if not FIX_MAPPING_PATH.exists():
            _fix_mapping = {}
        else:
            try:
                loaded = _load_joblib_file(FIX_MAPPING_PATH)
            except Exception as exc:
                logger.warning(
                    "failure_prediction.fix_mapping_load_failed",
                    error_type=exc.__class__.__name__,
                    fix_mapping_path=str(FIX_MAPPING_PATH),
                )
                _fix_mapping = {}
            else:
                _fix_mapping = loaded if isinstance(loaded, dict) else {}
    return _fix_mapping


def _suggested_fix_for(label: str) -> str:
    return _get_fix_mapping().get(label) or DEFAULT_FIX


def _prediction_confidence(model: Any, log_text: str) -> float | None:
    """Return max class probability when the model supports it."""
    if not hasattr(model, "predict_proba"):
        return None

    try:
        probabilities = model.predict_proba([log_text])
    except Exception as exc:
        logger.warning(
            "failure_prediction.confidence_failed",
            error_type=exc.__class__.__name__,
            log_length=len(log_text),
        )
        return None

    if len(probabilities) == 0 or len(probabilities[0]) == 0:
        return None
    try:
        values = [float(value) for value in probabilities[0]]
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in values):
            return None
        return round(max(values), 4)
    except (ValueError, TypeError):
        return None


def _safe_label(prediction: Any) -> str:
    """Extract a non-empty label from model output, falling back safely."""
    try:
        label = str(prediction[0]).strip()
    except Exception:
        return UNKNOWN_LABEL
    return label or UNKNOWN_LABEL


def predict_failure(log_text: str) -> dict:
    """Classify a CI/CD failure log and return a remediation hint."""
    if log_text is not None and not isinstance(log_text, str):
        raise ValueError("Failure log must be text.")
    cleaned_log = (log_text or "").strip()
    if not cleaned_log:
        recommendation = get_fix_recommendation(UNKNOWN_LABEL, cleaned_log)
        return {
            "label": UNKNOWN_LABEL,
            "confidence": None,
            "suggested_fix": _suggested_fix_for(UNKNOWN_LABEL),
            "recommendation": recommendation,
        }

    model = _get_model()
    try:
        label = _safe_label(model.predict([cleaned_log]))
        confidence = _prediction_confidence(model, cleaned_log)
    except FailurePredictionUnavailable:
        raise
    except Exception as exc:
        logger.error(
            "failure_prediction.predict_failed",
            error_type=exc.__class__.__name__,
            log_length=len(cleaned_log),
        )
        raise FailurePredictionError("Failure prediction failed. Please try again.") from exc

    suggested_fix = _suggested_fix_for(label)
    recommendation = get_fix_recommendation(label, cleaned_log)
    return {
        "label": label,
        "confidence": confidence,
        "suggested_fix": suggested_fix,
        "recommendation": recommendation,
    }
