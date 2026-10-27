import { getDebugHint, getUserFriendlyError } from "@/lib/errorMessages";
import {
  repositoryService,
  type RepositoryScanResult,
  type WorkflowPRResult,
} from "@/services/api";
import {
  AlertCircle,
  ExternalLink,
  GitBranch,
  GitPullRequest,
  Loader2,
  Radar,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";

function stackSummary(stack: RepositoryScanResult["stack"]) {
  return [
    stack.language,
    stack.framework,
    stack.package_manager,
    stack.has_docker ? "Docker" : null,
    stack.has_existing_workflows ? "existing workflow" : null,
  ]
    .filter(Boolean)
    .join(" / ");
}

function StackPanel({ result }: { result: RepositoryScanResult }) {
  const ciWarnings = result.stack.ci_warnings ?? [];

  return (
    <div className="rounded-2xl border border-surface-600 bg-surface-900/70 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
            Detected Stack
          </p>
          <p className="mt-2 text-sm font-semibold text-ink">
            {stackSummary(result.stack)}
          </p>
        </div>
        <span className="badge-info">{result.stack.recommended_workflow}</span>
      </div>
      <div className="mt-4 grid gap-3 text-sm text-ink-subtle sm:grid-cols-2 lg:grid-cols-4">
        <span>
          Language: <span className="text-ink">{result.stack.language}</span>
        </span>
        <span>
          Framework: <span className="text-ink">{result.stack.framework}</span>
        </span>
        <span>
          Package:{" "}
          <span className="text-ink">{result.stack.package_manager}</span>
        </span>
        <span>
          Files: <span className="text-ink">{result.files.length}</span>
        </span>
        <span>
          Directory:{" "}
          <span className="text-ink">{result.stack.project_dir || "."}</span>
        </span>
      </div>
      {result.stack.detected_projects.length > 1 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {result.stack.detected_projects.map((project) => (
            <span
              key={`${project.type}-${project.path}`}
              className="badge-info"
            >
              {project.type}: {project.path}
            </span>
          ))}
        </div>
      )}
      {ciWarnings.length > 0 && (
        <div className="mt-4 space-y-2">
          {ciWarnings.map((warning) => (
            <div
              key={`${warning.path}-${warning.issue}`}
              className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-100"
            >
              <p className="font-medium">{warning.path}</p>
              <p className="mt-1">{warning.issue}</p>
              <p className="mt-1 text-xs opacity-90">
                {warning.recommendation}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ReadinessPanel({ result }: { result: RepositoryScanResult }) {
  const { readiness } = result;
  const scoreColor =
    readiness.score >= 80
      ? "text-emerald-500"
      : readiness.score >= 60
        ? "text-amber-500"
        : "text-red-500";

  return (
    <div className="rounded-2xl border border-surface-600 bg-surface-900/70 p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
            CI/CD Readiness
          </p>
          <p className="mt-2 text-sm text-ink-subtle">{readiness.summary}</p>
        </div>
        <div className="text-right">
          <p className={`text-3xl font-semibold ${scoreColor}`}>
            {readiness.score}
          </p>
          <p className="text-xs text-ink-subtle">Grade {readiness.grade}</p>
        </div>
      </div>

      {readiness.strengths.length > 0 && (
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          {readiness.strengths.slice(0, 4).map((strength) => (
            <div
              key={strength}
              className="flex items-start gap-2 rounded-md border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-800 dark:text-emerald-100"
            >
              <ShieldCheck size={15} className="mt-0.5 shrink-0" />
              <span>{strength}</span>
            </div>
          ))}
        </div>
      )}

      {readiness.findings.length > 0 && (
        <div className="mt-4 space-y-2">
          {readiness.findings.slice(0, 4).map((finding) => (
            <div
              key={`${finding.category}-${finding.title}`}
              className="rounded-md border border-surface-600 bg-surface-800/60 px-3 py-2 text-sm"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="badge-info">{finding.severity}</span>
                <p className="font-medium text-ink">{finding.title}</p>
              </div>
              <p className="mt-1 text-ink-subtle">{finding.detail}</p>
              <p className="mt-1 text-xs text-ink-subtle">
                {finding.recommendation}
              </p>
            </div>
          ))}
        </div>
      )}

      {readiness.recommended_next_actions.length > 0 && (
        <div className="mt-4">
          <p className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
            Next Actions
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-subtle">
            {readiness.recommended_next_actions.slice(0, 4).map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function RepositorySetupPage() {
  const [params, setParams] = useSearchParams();
  const accountId = useAuthStore((state) => state.user?.id);
  const [repoFullName, setRepoFullName] = useState(params.get("repo") || "");
  const [scanResult, setScanResult] = useState<RepositoryScanResult | null>(
    null,
  );
  const [prResult, setPrResult] = useState<WorkflowPRResult | null>(null);
  const [scanning, setScanning] = useState(false);
  const [creatingPr, setCreatingPr] = useState(false);
  const [overwriteWorkflow, setOverwriteWorkflow] = useState(
    params.get("overwrite") === "true",
  );
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [gitHubConfigured, setGitHubConfigured] = useState<boolean | null>(
    null,
  );

  const normalizedRepo = repoFullName.trim();
  const selectedApproval = params.get("approval");
  const awaitingApproval = Boolean(prResult?.approval_required);

  useEffect(() => {
    const controller = new AbortController();
    void repositoryService
      .integrationStatus(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted)
          setGitHubConfigured(data.credentials_configured);
      })
      .catch(() => {});
    return () => controller.abort();
  }, [accountId]);

  useEffect(() => {
    if (!/^[\w.-]+\/[\w.-]+$/.test(normalizedRepo)) return;
    const controller = new AbortController();
    let busy = false;
    const refresh = async () => {
      if (busy) return;
      busy = true;
      try {
        const result = await repositoryService.workflowPrStatus(
          normalizedRepo,
          overwriteWorkflow,
          controller.signal,
          selectedApproval,
        );
        if (!controller.signal.aborted) setPrResult(result);
      } catch (err: unknown) {
        if (!controller.signal.aborted) setError(getUserFriendlyError(err));
      } finally {
        busy = false;
      }
    };
    const initial = window.setTimeout(refresh, 350);
    const poll = awaitingApproval ? window.setInterval(refresh, 4000) : null;
    window.addEventListener("focus", refresh);
    return () => {
      controller.abort();
      window.clearTimeout(initial);
      if (poll) window.clearInterval(poll);
      window.removeEventListener("focus", refresh);
    };
  }, [
    normalizedRepo,
    overwriteWorkflow,
    awaitingApproval,
    reload,
    accountId,
    selectedApproval,
  ]);

  const scanRepository = async () => {
    if (!normalizedRepo || scanning) return;
    setScanning(true);
    setError("");
    setParams(
      {
        repo: normalizedRepo,
        ...(overwriteWorkflow ? { overwrite: "true" } : {}),
      },
      { replace: true },
    );
    try {
      const result = await repositoryService.scan(normalizedRepo);
      setScanResult(result);
    } catch (err: any) {
      setScanResult(null);
      setError(getUserFriendlyError(err));
    } finally {
      setScanning(false);
    }
  };

  const createWorkflowPr = async () => {
    if (!normalizedRepo || creatingPr) return;
    setParams(
      {
        repo: normalizedRepo,
        ...(overwriteWorkflow ? { overwrite: "true" } : {}),
      },
      { replace: true },
    );
    setCreatingPr(true);
    setError("");
    try {
      const result = await repositoryService.createWorkflowPr(
        normalizedRepo,
        overwriteWorkflow,
      );
      setPrResult(result);
      setReload((current) => current + 1);
      if (result.detected_stack) {
        setScanResult(
          (current) =>
            current || {
              repo_full_name: result.repo_full_name,
              files: [],
              stack: result.detected_stack!,
              readiness: {
                score: 0,
                grade: "N/A",
                summary: "Scan the repository to view CI/CD readiness.",
                strengths: [],
                findings: [],
                recommended_next_actions: [],
              },
            },
        );
      }
    } catch (err: any) {
      setError(getUserFriendlyError(err));
    } finally {
      setCreatingPr(false);
    }
  };

  return (
    <div className="flex h-full flex-col bg-surface-900">
      <div className="workspace-page-header shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-primary-500/30 bg-primary-500/10">
            <GitPullRequest
              size={19}
              className="text-primary-600 dark:text-primary-300"
            />
          </div>
          <div>
            <h1 className="text-base font-semibold text-ink">
              Repository CI/CD Setup
            </h1>
            <p className="text-xs text-ink-subtle">
              Scan a GitHub repository and open a workflow setup pull request
            </p>
          </div>
        </div>
      </div>

      <div className="workspace-page-body min-h-0 flex-1 overflow-y-auto py-5">
        <div className="mx-auto max-w-5xl space-y-5">
          <section className="card p-5">
            <label
              htmlFor="repo-full-name"
              className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-subtle"
            >
              Repository
            </label>
            <div className="mt-3 flex flex-col gap-3 sm:flex-row">
              <input
                id="repo-full-name"
                value={repoFullName}
                onChange={(event) => {
                  setRepoFullName(event.target.value);
                  if (selectedApproval) setParams({}, { replace: true });
                  setScanResult(null);
                  setPrResult(null);
                  setError("");
                }}
                disabled={scanning || creatingPr}
                className="input-field flex-1"
                placeholder="owner/repository"
              />
              <button
                type="button"
                onClick={scanRepository}
                disabled={!normalizedRepo || scanning}
                className="btn-primary min-h-11 w-full sm:w-auto"
              >
                {scanning ? (
                  <Loader2 size={15} className="animate-spin" />
                ) : (
                  <Radar size={15} />
                )}
                Scan Repository
              </button>
            </div>
            <p className="mt-3 text-xs leading-5 text-ink-subtle">
              GitHub scanning and pull request creation require a backend
              GITHUB_TOKEN or GitHub App credentials. Token values stay in the
              backend environment and are never shown here.
            </p>
            {gitHubConfigured === false && (
              <div
                role="status"
                className="mt-4 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-200"
              >
                GitHub access is not connected. Ask your admin to connect the
                repository before scanning or sending a pull request. Approval
                requests can still be saved for review.
              </div>
            )}
            {error && (
              <div className="mt-4 rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-200">
                <div className="flex items-start gap-2">
                  <AlertCircle size={16} className="mt-0.5 shrink-0" />
                  <div>
                    <p className="font-semibold">{error}</p>
                    {getDebugHint(error) && (
                      <p className="mt-1 text-xs opacity-80">
                        Tip: {getDebugHint(error)}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            )}
          </section>

          {scanResult && (
            <section className="card p-5">
              <div className="space-y-4">
                <StackPanel result={scanResult} />
                <ReadinessPanel result={scanResult} />
              </div>
              <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
                <button
                  type="button"
                  onClick={createWorkflowPr}
                  disabled={!normalizedRepo || creatingPr || awaitingApproval}
                  className="btn-primary w-full sm:w-auto"
                >
                  {creatingPr ? (
                    <Loader2 size={15} className="animate-spin" />
                  ) : (
                    <GitPullRequest size={15} />
                  )}
                  Create Workflow PR
                </button>
                <span className="text-xs text-ink-subtle">
                  Saves a review request. After approval, creates a branch and
                  opens a pull request.
                </span>
              </div>
              <label className="mt-4 flex items-start gap-3 text-sm text-ink-subtle">
                <input
                  type="checkbox"
                  checked={overwriteWorkflow}
                  disabled={creatingPr}
                  onChange={(event) => {
                    setOverwriteWorkflow(event.target.checked);
                    setParams(
                      {
                        repo: normalizedRepo,
                        ...(event.target.checked ? { overwrite: "true" } : {}),
                      },
                      { replace: true },
                    );
                    setPrResult(null);
                  }}
                  className="mt-1 h-4 w-4 rounded border-surface-500 bg-surface-800 text-primary-600 focus:ring-primary-500"
                />
                <span>
                  Replace existing AI-generated workflow file in the pull
                  request branch
                </span>
              </label>
            </section>
          )}

          {prResult && (
            <section className="card p-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
                    {prResult.approval_required ||
                    prResult.status === "approval_required"
                      ? "Approval Required"
                      : prResult.pull_request_url
                        ? "Pull Request Created"
                        : `Request ${prResult.status || "status"}`}
                  </p>
                  <h2 className="mt-2 text-base font-semibold text-ink">
                    {prResult.repo_full_name}
                  </h2>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {prResult.workflow_path && (
                      <span className="badge-success">
                        {prResult.workflow_path}
                      </span>
                    )}
                    {prResult.branch && (
                      <span className="badge-info inline-flex items-center gap-1">
                        <GitBranch size={12} /> {prResult.branch}
                      </span>
                    )}
                    {prResult.approval_id && (
                      <span className="badge-info inline-flex items-center gap-1">
                        <ShieldCheck size={12} /> {prResult.approval_id}
                      </span>
                    )}
                  </div>
                  {prResult.message && (
                    <p className="mt-3 text-sm text-ink-subtle">
                      {prResult.message}
                    </p>
                  )}
                  <button
                    type="button"
                    onClick={() => setReload((current) => current + 1)}
                    className="btn-secondary mt-3"
                  >
                    <RefreshCw size={14} /> Refresh PR status
                  </button>
                  {!prResult.approval_required &&
                    !prResult.pull_request_url && (
                      <button
                        type="button"
                        onClick={createWorkflowPr}
                        disabled={creatingPr}
                        className="btn-primary mt-3 ml-2"
                      >
                        {creatingPr && (
                          <Loader2 size={14} className="animate-spin" />
                        )}{" "}
                        Request a new review
                      </button>
                    )}
                  {prResult.workflow_path && (
                    <p className="mt-3 text-sm text-ink-subtle">
                      Generated workflow path:{" "}
                      <span className="font-mono text-ink">
                        {prResult.workflow_path}
                      </span>
                    </p>
                  )}
                </div>
                {(prResult.approval_required ||
                  prResult.status === "approval_required") && (
                  <Link
                    to="/approvals"
                    className="btn-primary w-full sm:w-auto"
                  >
                    Review approval <ShieldCheck size={15} />
                  </Link>
                )}
                {prResult.pull_request_url && (
                  <a
                    href={prResult.pull_request_url}
                    target="_blank"
                    rel="noreferrer"
                    className="btn-secondary w-full sm:w-auto"
                  >
                    Open PR <ExternalLink size={15} />
                  </a>
                )}
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
