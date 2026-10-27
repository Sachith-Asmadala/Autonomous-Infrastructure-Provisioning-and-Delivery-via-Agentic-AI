# Smart DevOps Assistant: code learning and interview guide

Reviewed snapshot: `e4c9732db1e7985dd9f52a203193876145aa27c4`. This guide explains existing source. It does not claim a production deployment, successful infrastructure provisioning, or new model-quality measurements.

## Problem and implemented scope

This project helps inspect CI failures, classify log text, recommend fixes, generate workflow YAML, and propose GitHub changes through approval-controlled flows. The implementation combines FastAPI, SQLAlchemy, React/TypeScript, a scikit-learn log classifier, GitHub integrations, and orchestration/specialized-agent classes. Repository naming is broader than the demonstrated MVP: do not present it as proof of autonomous production infrastructure management.

## Startup and component map

[backend/app/main.py](https://github.com/Sachith-Asmadala/Autonomous-Infrastructure-Provisioning-and-Delivery-via-Agentic-AI/blob/e4c9732db1e7985dd9f52a203193876145aa27c4/backend/app/main.py) sets up logging, FastAPI, CORS, and API routers. Its lifespan calls `init_db()`. That function creates missing tables, applies demo compatibility changes, and attempts default-user setup. It catches initialization errors and logs a warning, so a responding web process alone does not prove the database is healthy.

The frontend mounts a React application, provides pages/routes and state stores, and uses `frontend/src/services/api.ts` to communicate with the API. Backend routes validate requests and permissions, then call services/agents/tools. SQLAlchemy stores application/audit/approval data. Model artifacts are loaded lazily; inference does not retrain the model on each request.

| Component | Important code |
| --- | --- |
| API endpoints and schemas | `backend/app/api/routes/`, `backend/app/schemas/schemas.py` |
| Deterministic agent routing | [backend/app/agents/orchestration_agent.py](https://github.com/Sachith-Asmadala/Autonomous-Infrastructure-Provisioning-and-Delivery-via-Agentic-AI/blob/e4c9732db1e7985dd9f52a203193876145aa27c4/backend/app/agents/orchestration_agent.py) |
| Specialized behavior | `cli_agent.py`, `cicd_agent.py`, `diagnosis_agent.py`, `github_agent.py` in the same directory |
| Log inference | [backend/app/services/failure_prediction_service.py](https://github.com/Sachith-Asmadala/Autonomous-Infrastructure-Provisioning-and-Delivery-via-Agentic-AI/blob/e4c9732db1e7985dd9f52a203193876145aa27c4/backend/app/services/failure_prediction_service.py) |
| Training and evaluation implementation | `backend/app/ml/train_failure_model.py` |
| GitHub API operations | `backend/app/tools/github_tool.py` and integration services |
| Human review and audit | `backend/app/api/routes/approvals.py`, `backend/app/services/audit_service.py` |

`OrchestrationAgent.handle()` prepares an `AgentTask`, selects one specialized route, calls its handler, and attaches trace metadata to an `AgentResult`. This is application-level agent routing; it is not evidence that several agents execute concurrently. The legacy chat path is also present, so identify which endpoint a demonstration uses.

## Walkthrough: classify a pasted CI error

Use the bounded prediction endpoint to learn the path before attempting any GitHub write.

1. Frontend `cicdAssistantService.predictFailure` sends `{log_text: ...}` to `/api/v1/model/predict-failure` through its shared API client. An example input is `npm ERR! Missing script: test`.
2. [routes/model.py](https://github.com/Sachith-Asmadala/Autonomous-Infrastructure-Provisioning-and-Delivery-via-Agentic-AI/blob/e4c9732db1e7985dd9f52a203193876145aa27c4/backend/app/api/routes/model.py) requires the `failures:predict` permission and parses `FailurePredictionRequest`. The schema limits `log_text` to 20,000 characters.
3. `predict_failure()` strips whitespace. Empty text returns `unknown_failure` with no confidence. Nonempty text loads the configured joblib model through `_get_model()`, caching it in the process.
4. The trained pipeline converts log text into TF-IDF features, then applies logistic regression. Training code uses word unigrams/bigrams, balanced class weights, a repeatable split, and also compares a LinearSVC baseline.
5. The service extracts a label, obtains a maximum class probability when supported, finds a label-to-fix suggestion, and builds a structured recommendation. It returns a dictionary containing `label`, `confidence`, `suggested_fix`, and `recommendation`.
6. The endpoint records prediction/recommendation audit events and returns the response. Missing/unloadable model artifacts produce a 503; prediction failures produce a controlled 500 response.
7. The frontend displays the diagnosis. This endpoint does not execute the suggestion or create a pull request. Those are separate, permission/approval-sensitive paths.

The sample input's real predicted label depends on the installed artifact. Existing tests substitute a fake classifier to check response behavior; their hardcoded probabilities are not measured real-world accuracy.

## Data structures and engineering decisions

Pydantic request/result models provide validated API shapes. `AgentTask.context` is a dictionary for task context; `AgentResult.metadata` holds trace/recommendation information. Lists carry repository paths and steps. A dictionary maps labels to suggested fixes. TF-IDF produces sparse numeric feature vectors, keeping a simple text classifier practical for a small failure taxonomy. ORM models persist approvals and executions rather than relying only on browser state.

Separating prediction, recommendation, and execution makes the system easier to inspect. Deterministic routing and approval planning expose the selected tool/action. A cached model reduces repeated disk loading, but changing the artifact requires considering process-cache invalidation. Joblib artifacts must come from trusted sources; loading an arbitrary untrusted serialized model is unsafe.

## Error handling, limits, and improvements

`FailurePredictionUnavailable` separates missing model/runtime dependencies from prediction errors. The specialized `DiagnosisAgent` converts these into unsuccessful structured results. The route returns controlled HTTP failures, and logs generally record error type/log length rather than dumping full provider errors in this path. Review other paths separately before making an application-wide security claim.

Confidence is a model probability, not proof that the diagnosis or fix is correct. A limited training dataset can overstate generalization. Validate on held-out logs from different repositories and check class balance/leakage before advertising performance. Small or single-class datasets can still challenge training despite split safeguards. Inference is synchronous work inside an async endpoint; measure latency before deciding whether to use a thread pool or background work.

Existing `backend/tests/test_failure_prediction.py` checks empty logs, fake predictions, unknown labels, missing artifacts, runtime failures, authentication, and endpoint behavior. Other tests cover agents and approval flows. This guide does not rerun them or certify live GitHub writes. Learn the proposal/approval path before using a real token or target repository.

## Contribution evidence

GitHub attributes [commit eb4008f](https://github.com/Sachith-Asmadala/Autonomous-Infrastructure-Provisioning-and-Delivery-via-Agentic-AI/commit/eb4008f3ded6b66835e2da57c23cfe972530e547) to `Sachith-Asmadala`. Its diff includes approval-controlled workflow PR work, routing, schemas, tests, and documentation. Confirm your exact responsibilities and assistance. Neither fork ownership nor this account-attributed commit establishes sole authorship of the entire assistant.

## Five interview questions and model answers

1. **Why use TF-IDF and logistic regression?** The code uses a simple, inspectable text-classification pipeline with probability support. It is a baseline for known failure categories, not a general root-cause proof engine.
2. **Does a 90% confidence value mean the fix is safe?** No. It is the model's class probability estimate. Distribution shift and misclassification remain possible, and execution safety requires separate checks/approval.
3. **Does application startup train the model?** No. Inference loads existing artifacts lazily and caches them. Training is a separate script that writes artifacts and evaluation files.
4. **Why separate diagnosis from GitHub execution?** A read-only diagnosis can return advice without mutating a repository. Changes require additional permissions, a concrete proposed action, approval handling, and an audit trail.
5. **How would you test model-unavailable behavior?** Substitute a nonexistent artifact path and assert the service raises the unavailable exception and the endpoint returns 503. That verifies failure handling without a networked model or GitHub write.

## Practice

Draw request → schema → permission → prediction service → artifact → audit → response. Explain a false positive and how a human reviewer should handle it. Distinguish the direct model endpoint from orchestration and legacy chat before presenting a demo.
