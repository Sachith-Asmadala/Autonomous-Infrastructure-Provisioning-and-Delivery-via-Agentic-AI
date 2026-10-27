import { ImportFailureDialog } from "@/components/workflow-failures/ImportFailureDialog";
import { getDebugHint, getUserFriendlyError } from "@/lib/errorMessages";
import { hasPermission } from "@/lib/rbac";
import {
  workflowFailureService,
  type WorkflowFailure,
  type WorkflowFailureFixPRResult,
  type WorkflowFailureIntegrationStatus,
} from "@/services/api";
import { useAuthStore } from "@/store/authStore";
import { formatDistanceToNow } from "date-fns";
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  GitBranch,
  GitPullRequest,
  Loader2,
  RefreshCw,
  Download,
  FileText,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useState } from "react";

function relativeTime(value?: string | null) {
  if (!value) return "time unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "time unknown";
  return formatDistanceToNow(date, { addSuffix: true });
}

function formatConfidence(value: number | null) {
  if (value === null || Number.isNaN(value)) return "Not available";
  return `${Math.round(value * 100)}%`;
}

function statusBadge(status: string) {
  const classes: Record<string, string> = {
    diagnosed: "badge-success",
    diagnosis_failed: "badge-error",
    logs_unavailable: "badge-warning",
    pending: "badge-warning",
    fix_pr_created: "badge-success",
    approval_pending: "badge-warning",
    recommendation_only: "badge-info",
    rejected: "badge-error",
  };
  return (
    <span className={classes[status] || "badge-info"}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

function labelBadge(label: string | null) {
  if (!label) return <span className="badge-warning">unclassified</span>;
  return <span className="badge-info">{label}</span>;
}

function actionMessage(result: WorkflowFailureFixPRResult) {
  if (result.pull_request_url) return "Fix pull request created.";
  if (result.approval_id)
    return "Approval request created. Review it on the Approvals page.";
  return result.message;
}

function FailureDetails({
  failure,
  canCreateFixPr,
  creating,
  actionError,
  actionResult,
  onCreateFixPr,
  onImportLogs,
}: {
  failure: WorkflowFailure;
  canCreateFixPr: boolean;
  creating: boolean;
  actionError?: string;
  actionResult?: WorkflowFailureFixPRResult;
  onCreateFixPr: () => void;
  onImportLogs: () => void;
}) {
  const hasFixPr = Boolean(
    failure.fix_pr_url || actionResult?.pull_request_url,
  );
  const fixPrUrl = failure.fix_pr_url || actionResult?.pull_request_url;
  const isAwaitingApproval =
    failure.status === "approval_pending" &&
    failure.has_pending_approval !== false;
  const hasPrediction = Boolean(failure.predicted_label);

  return (
    <div className="border-t border-surface-600 bg-surface-900/70 px-4 py-4">
      {failure.diagnosis_error && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-200">
          <p>{failure.diagnosis_error}</p>
          <button
            className="btn-secondary"
            type="button"
            onClick={onImportLogs}
          >
            <FileText size={14} /> Paste run logs
          </button>
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-subtle">
            Log Excerpt
          </p>
          {failure.workflow_url && (
            <a
              href={failure.workflow_url}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary-700 dark:text-primary-300"
            >
              Open workflow run <ExternalLink size={13} />
            </a>
          )}
          <pre className="mt-2 max-h-56 max-w-full overflow-auto rounded-xl border border-surface-600 bg-surface-950 p-3 text-xs leading-5 text-ink">
            <code>{failure.log_excerpt || "No log excerpt stored."}</code>
          </pre>
        </div>
        <div className="space-y-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-subtle">
              Suggested Fix
            </p>
            <p className="mt-2 text-sm leading-6 text-ink">
              {failure.suggested_fix || "No suggested fix available."}
            </p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-subtle">
              Fix PR
            </p>
            {fixPrUrl ? (
              <a
                href={fixPrUrl}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-flex items-center gap-2 text-sm font-semibold text-primary-700 hover:text-primary-600 dark:text-primary-300"
              >
                Open pull request <ExternalLink size={14} />
              </a>
            ) : (
              <div className="mt-2 space-y-3">
                {isAwaitingApproval ? (
                  <div className="inline-flex items-center gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-200">
                    <ShieldCheck size={14} /> Waiting for human approval
                  </div>
                ) : (
                  <p className="text-sm text-ink-subtle">
                    No fix pull request has been created.
                  </p>
                )}
                {canCreateFixPr &&
                  hasPrediction &&
                  !hasFixPr &&
                  !isAwaitingApproval && (
                    <button
                      type="button"
                      onClick={onCreateFixPr}
                      disabled={creating}
                      className="btn-primary w-full sm:w-auto"
                    >
                      {creating ? (
                        <Loader2 size={15} className="animate-spin" />
                      ) : (
                        <GitPullRequest size={15} />
                      )}
                      Request fix PR
                    </button>
                  )}
                {!canCreateFixPr && !hasFixPr && (
                  <p className="text-xs text-ink-subtle">
                    You can request fixes for your own diagnosed failures.
                  </p>
                )}
              </div>
            )}
          </div>
          {actionResult && (
            <div className="rounded-xl border border-primary-500/30 bg-primary-500/10 px-3 py-2 text-sm text-primary-700 dark:text-primary-200">
              {actionMessage(actionResult)}
            </div>
          )}
          {actionError && (
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-200">
              <div className="flex items-start gap-2">
                <AlertCircle size={14} className="mt-0.5 shrink-0" />
                <div>
                  <p className="font-semibold">{actionError}</p>
                  {getDebugHint(actionError) && (
                    <p className="mt-1 text-xs opacity-80">
                      Tip: {getDebugHint(actionError)}
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function FailureRow({
  failure,
  canCreateFixPr,
  creating,
  actionError,
  actionResult,
  onCreateFixPr,
  onImportLogs,
}: {
  failure: WorkflowFailure;
  canCreateFixPr: boolean;
  creating: boolean;
  actionError?: string;
  actionResult?: WorkflowFailureFixPRResult;
  onCreateFixPr: (failure: WorkflowFailure) => void;
  onImportLogs: (failure: WorkflowFailure) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="card overflow-hidden">
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={`failure-${failure.id}`}
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-start gap-3 px-4 py-4 text-left transition-colors hover:bg-surface-800/80"
      >
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-300">
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="min-w-0 break-words text-sm font-semibold text-ink sm:truncate">
              {failure.repo_full_name}
            </p>
            {statusBadge(failure.status)}
            {labelBadge(failure.predicted_label)}
          </div>
          <div className="mt-2 grid gap-2 text-xs text-ink-subtle sm:grid-cols-2 xl:grid-cols-4">
            <span className="truncate">
              Workflow:{" "}
              <span className="text-ink">
                {failure.workflow_name || "Unknown"}
              </span>
            </span>
            <span className="flex min-w-0 items-center gap-1 truncate">
              <GitBranch size={13} />{" "}
              <span className="truncate text-ink">
                {failure.branch || "Unknown branch"}
              </span>
            </span>
            <span>
              Run ID:{" "}
              <span className="font-mono text-ink">
                {failure.workflow_run_id}
              </span>
            </span>
            <span>
              Saved:{" "}
              <span className="text-ink">
                {relativeTime(failure.created_at)}
              </span>
            </span>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-ink-subtle">
            <span>
              Confidence:{" "}
              <span className="font-semibold text-ink">
                {formatConfidence(failure.confidence)}
              </span>
            </span>
            <span>
              Recorded by:{" "}
              <span className="text-ink">
                {failure.requested_by || "System / legacy import"}
              </span>
            </span>
          </div>
        </div>
      </button>
      {expanded && (
        <div id={`failure-${failure.id}`}>
          <FailureDetails
            failure={failure}
            canCreateFixPr={canCreateFixPr}
            creating={creating}
            actionError={actionError}
            actionResult={actionResult}
            onCreateFixPr={() => onCreateFixPr(failure)}
            onImportLogs={() => onImportLogs(failure)}
          />
        </div>
      )}
    </div>
  );
}

export default function WorkflowFailuresPage() {
  const { user } = useAuthStore();
  const [failures, setFailures] = useState<WorkflowFailure[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [integration, setIntegration] =
    useState<WorkflowFailureIntegrationStatus | null>(null);
  const [reload, setReload] = useState(0);
  const [showImport, setShowImport] = useState(false);
  const [importFailure, setImportFailure] = useState<WorkflowFailure | null>(
    null,
  );
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [creatingFixPrId, setCreatingFixPrId] = useState<string | null>(null);
  const [actionErrors, setActionErrors] = useState<Record<string, string>>({});
  const [actionResults, setActionResults] = useState<
    Record<string, WorkflowFailureFixPRResult>
  >({});
  const canCreateFixPr = hasPermission(user?.role, "repositories:write");

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void workflowFailureService
      .list(200, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setFailures(data);
          setActionResults({});
          setActionErrors({});
        }
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setError(getUserFriendlyError(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    void workflowFailureService
      .integrationStatus(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setIntegration(data);
      })
      .catch(() => {
        /* Failure records still load if the capability probe fails. */
      });
    return () => controller.abort();
  }, [reload]);

  const visibleFailures = failures.filter((failure) =>
    `${failure.repo_full_name} ${failure.workflow_name || ""} ${failure.branch || ""} ${failure.predicted_label || ""} ${failure.workflow_run_id}`
      .toLowerCase()
      .includes(query.trim().toLowerCase()),
  );
  const openImport = (failure: WorkflowFailure | null = null) => {
    setImportFailure(failure);
    setShowImport(true);
  };

  const createFixPr = async (failure: WorkflowFailure) => {
    if (creatingFixPrId) return;
    setCreatingFixPrId(failure.id);
    setActionErrors((current) => ({ ...current, [failure.id]: "" }));
    try {
      const result = await workflowFailureService.createFixPr(failure.id);
      setActionResults((current) => ({ ...current, [failure.id]: result }));
      setFailures((current) =>
        current.map((item) => {
          if (item.id !== failure.id) return item;
          return {
            ...item,
            status:
              result.status === "approval_required"
                ? "approval_pending"
                : result.status,
            fix_pr_url: result.pull_request_url || item.fix_pr_url,
            has_pending_approval: result.status === "approval_required",
            updated_at: new Date().toISOString(),
          };
        }),
      );
    } catch (err: any) {
      setActionErrors((current) => ({
        ...current,
        [failure.id]: getUserFriendlyError(err),
      }));
    } finally {
      setCreatingFixPrId(null);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="workspace-page-header shrink-0">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-red-500/30 bg-red-500/10">
              <TriangleAlert
                size={19}
                className="text-red-600 dark:text-red-300"
              />
            </div>
            <div>
              <h1 className="text-base font-semibold text-ink">
                Workflow Failures
              </h1>
              <p className="text-xs text-ink-subtle">
                {user?.role === "admin"
                  ? "Failed runs across the workspace"
                  : "Your imported runs and failure diagnoses"}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => openImport()}
              className="btn-primary"
            >
              <Download size={14} /> Import failures
            </button>
            <button
              type="button"
              onClick={() => setReload((value) => value + 1)}
              disabled={loading}
              className="btn-ghost border border-surface-600"
            >
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} />{" "}
              Refresh
            </button>
          </div>
        </div>
      </div>

      <div className="workspace-page-body min-h-0 flex-1 overflow-y-auto py-5">
        <div className="mx-auto mb-5 max-w-6xl space-y-3">
          {notice && (
            <div
              role="status"
              className="rounded-xl border border-primary-500/30 bg-primary-500/10 p-3 text-sm text-primary-700 dark:text-primary-200"
            >
              {notice}
            </div>
          )}
          {integration && !integration.can_download_logs && (
            <div className="rounded-xl border border-surface-600 bg-surface-800 p-4 text-sm leading-6 text-ink-muted">
              <p className="font-medium text-ink">
                Automatic log download is not connected.
              </p>
              <p>
                Import public failed runs from GitHub, then paste their logs for
                diagnosis. Your admin can configure GitHub access to download
                logs automatically.
              </p>
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <input
              aria-label="Search workflow failures"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search repository, branch, diagnosis or run ID…"
              className="input-field w-full max-w-lg px-3 py-2.5"
            />
            <span className="text-xs text-ink-subtle">
              {visibleFailures.length} of {failures.length} saved failures
            </span>
          </div>
        </div>
        {loading ? (
          <div className="flex h-40 items-center justify-center">
            <Loader2 size={24} className="animate-spin text-primary-500" />
          </div>
        ) : error ? (
          <div className="mx-auto max-w-3xl rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-red-700 dark:text-red-200">
            <div className="flex items-start gap-3">
              <AlertCircle size={18} className="mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-semibold">{error}</p>
                {getDebugHint(error) && (
                  <p className="mt-2 text-xs opacity-80">
                    Tip: {getDebugHint(error)}
                  </p>
                )}
              </div>
            </div>
          </div>
        ) : failures.length === 0 ? (
          <div className="flex min-h-[280px] flex-col items-center justify-center text-center">
            <div className="mb-4 rounded-3xl border border-surface-600 bg-surface-800 p-4">
              <TriangleAlert size={40} className="text-ink-subtle" />
            </div>
            <p className="font-medium text-ink">No workflow failures yet</p>
            <p className="mt-1 text-sm text-ink-subtle">
              Import an existing failed run or paste its logs to save a
              diagnosis.
            </p>
            <button
              className="btn-primary mt-5"
              type="button"
              onClick={() => openImport()}
            >
              <Download size={15} /> Import your first failed run
            </button>
          </div>
        ) : visibleFailures.length === 0 ? (
          <p className="py-12 text-center text-sm text-ink-subtle">
            No failures match your search.
          </p>
        ) : (
          <div className="mx-auto max-w-6xl space-y-3">
            {visibleFailures.map((failure) => (
              <FailureRow
                key={failure.id}
                failure={failure}
                canCreateFixPr={canCreateFixPr}
                creating={creatingFixPrId === failure.id}
                actionError={actionErrors[failure.id]}
                actionResult={actionResults[failure.id]}
                onCreateFixPr={createFixPr}
                onImportLogs={openImport}
              />
            ))}
          </div>
        )}
      </div>
      {showImport && (
        <ImportFailureDialog
          defaultRepository={integration?.default_repository}
          failure={importFailure}
          onClose={() => setShowImport(false)}
          onImported={(message) => {
            setNotice(message);
            setQuery("");
            setReload((value) => value + 1);
          }}
        />
      )}
    </div>
  );
}
