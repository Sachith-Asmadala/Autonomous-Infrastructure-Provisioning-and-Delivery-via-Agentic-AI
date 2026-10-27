import { getDebugHint, getUserFriendlyError } from "@/lib/errorMessages";
import { hasPermission } from "@/lib/rbac";
import { useAuthStore } from "@/store/authStore";
import type { User } from "@/types";
import { approvalService } from "@/services/api";
import { formatDistanceToNow } from "date-fns";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle,
  Clock,
  ExternalLink,
  Loader2,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

interface Approval {
  id: string;
  description?: string;
  action?: string;
  summary?: string;
  requested_by?: string;
  risk_level?: string;
  tool_name?: string;
  tool_input?: string;
  payload?: string;
  status: string;
  expires_at?: string;
  created_at: string;
  can_approve?: boolean;
  can_reject?: boolean;
}

interface ApprovalDetails {
  repository?: string;
  workflow_run_id?: number;
  predicted_failure?: string;
  suggested_fix?: string;
  proposed_file_changes?: string[];
  risk_level?: string;
  workflow_path?: string;
  workflow_url?: string;
}

function relativeTime(value?: string) {
  if (!value) return "time unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "time unknown";
  return formatDistanceToNow(date, { addSuffix: true });
}

function parseApprovalDetails(approval: Approval): ApprovalDetails | null {
  const raw = approval.tool_input || approval.payload;
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    return parsed.approval_details || parsed;
  } catch {
    return null;
  }
}

function DetailRow({
  label,
  value,
}: {
  label: string;
  value?: string | number | null;
}) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <div>
      <dt className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">
        {label}
      </dt>
      <dd className="mt-1 break-words text-sm text-ink">{value}</dd>
    </div>
  );
}

export default function ApprovalsPage() {
  const user = useAuthStore((state) => state.user);
  return <ApprovalsContent key={`${user?.id}:${user?.role}`} user={user} />;
}

function ApprovalsContent({ user }: { user: User | null }) {
  const canReviewShared = hasPermission(user?.role, "approvals:decide");
  const canReviewOwn = hasPermission(user?.role, "approvals:decide:own");
  const canDecide = canReviewShared || canReviewOwn;
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [decisionMessage, setDecisionMessage] = useState("");
  const [decisionPrUrl, setDecisionPrUrl] = useState("");
  const [decisionRepository, setDecisionRepository] = useState("");

  function parsedDetails(raw?: string): Record<string, unknown> {
    try {
      const value = JSON.parse(raw || "{}");
      return value && typeof value === "object" && !Array.isArray(value)
        ? value
        : {};
    } catch {
      return {};
    }
  }
  const [decidingId, setDecidingId] = useState<string | null>(null);

  const fetchApprovals = async () => {
    setLoading(true);
    setError("");
    try {
      const data: Approval[] = await approvalService.list(
        canReviewShared ? "all" : "mine",
      );
      setApprovals(
        data.filter(
          (approval) =>
            canReviewShared ||
            approval.requested_by === (user?.username || user?.id),
        ),
      );
    } catch (err: any) {
      setError(getUserFriendlyError(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchApprovals();
  }, []);

  const canDecideRequest = (approval: Approval, approved: boolean) => {
    if (!canDecide || approval.status !== "pending") return false;
    if (
      approval.tool_name === "admin_set_user_active" &&
      !hasPermission(user?.role, "users:manage")
    )
      return false;
    if (
      !canReviewShared &&
      approval.requested_by !== (user?.username || user?.id)
    )
      return false;
    return (
      (approved ? approval.can_approve : approval.can_reject) ?? canReviewShared
    );
  };

  const decide = async (approval: Approval, approved: boolean) => {
    if (decidingId || !canDecideRequest(approval, approved)) return;
    setDecisionMessage("");
    setDecisionPrUrl("");
    setDecisionRepository("");
    setDecidingId(approval.id);
    setError("");
    try {
      const result = await approvalService.decide(approval.id, approved);
      const details = parsedDetails(result.execution_details);
      const target = parsedDetails(approval.tool_input || approval.payload);
      const repository = details.repo_full_name || target.repo_full_name;
      if (
        typeof repository === "string" &&
        approval.tool_name === "github_create_workflow_pr"
      ) {
        const query = new URLSearchParams({
          repo: repository,
          approval: approval.id,
        });
        if (target.overwrite_existing_workflow === true)
          query.set("overwrite", "true");
        setDecisionRepository(`/repository-setup?${query}`);
      }
      if (
        result.execution_status === "completed" &&
        typeof details.pull_request_url === "string" &&
        /^https:\/\/github\.com\//.test(details.pull_request_url)
      )
        setDecisionPrUrl(details.pull_request_url);
      await fetchApprovals();
      if (approved && result.execution_status === "failed") {
        setError(
          `Approval was recorded, but execution failed. ${typeof details.error === "string" ? details.error : "Open the audit log for details."}`,
        );
      } else {
        setDecisionMessage(
          approved
            ? result.execution_status === "completed"
              ? "Approved. The action completed."
              : "Approval recorded. Check the audit log for the execution result."
            : "Rejected. The action was cancelled.",
        );
      }
    } catch (err: any) {
      setError(getUserFriendlyError(err));
    } finally {
      setDecidingId(null);
    }
  };

  return (
    <div className="flex h-full flex-col bg-surface-900">
      <div className="workspace-page-header shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-amber-500/30 bg-amber-500/10">
            <ShieldCheck
              size={19}
              className="text-amber-600 dark:text-amber-300"
            />
          </div>
          <div>
            <h1 className="text-base font-semibold text-ink">
              {canReviewShared
                ? "Approval review queue"
                : canReviewOwn
                  ? "Your approval review queue"
                  : "Your approval requests"}
            </h1>
            <p className="text-xs text-ink-subtle">
              {canReviewShared
                ? "Review high-risk requests before execution"
                : canReviewOwn
                  ? "Approve or reject your own work. Privileged actions need an admin."
                  : "Track your requests waiting for an admin to review"}
            </p>
          </div>
        </div>
      </div>
      <div className="workspace-page-body min-h-0 flex-1 overflow-y-auto py-5">
        {(decisionPrUrl || decisionRepository) && (
          <div className="mx-auto mb-4 flex max-w-3xl flex-wrap gap-3">
            {decisionPrUrl && (
              <a
                href={decisionPrUrl}
                target="_blank"
                rel="noreferrer"
                className="btn-primary"
              >
                Open PR <ExternalLink size={14} />
              </a>
            )}
            {decisionRepository && (
              <Link to={decisionRepository} className="btn-secondary">
                Check repository PR status
              </Link>
            )}
          </div>
        )}
        {decisionMessage && (
          <div
            role="status"
            className="mx-auto mb-4 flex max-w-3xl flex-wrap items-center justify-between gap-3 rounded-xl border border-primary-500/30 bg-primary-500/10 p-4 text-sm text-primary-700 dark:text-primary-200"
          >
            <span>{decisionMessage}</span>
            <Link to="/executions" className="font-medium underline">
              View audit log
            </Link>
          </div>
        )}
        {loading ? (
          <div className="flex h-32 items-center justify-center">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
          </div>
        ) : error ? (
          <div className="mx-auto max-w-3xl">
            <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-red-700 dark:text-red-200">
              <div className="flex items-start gap-3">
                <AlertCircle size={18} className="mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-semibold">{error}</p>
                  <Link
                    to="/executions"
                    className="mt-2 inline-block text-xs underline"
                  >
                    View audit log
                  </Link>
                  {getDebugHint(error) && (
                    <p className="mt-2 text-xs opacity-80">
                      Tip: {getDebugHint(error)}
                    </p>
                  )}
                </div>
              </div>
            </div>
          </div>
        ) : approvals.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <div className="mb-4 rounded-3xl border border-primary-500/25 bg-primary-500/10 p-4">
              <CheckCircle
                size={40}
                className="text-primary-600 dark:text-primary-300"
              />
            </div>
            <p className="font-medium text-ink">No pending approvals</p>
            <p className="mt-1 text-sm text-ink-subtle">
              High-risk agent actions will appear here for your review.
            </p>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-4">
            {approvals.map((a) => {
              const description =
                a.description ||
                a.action ||
                a.summary ||
                "Approval requested by the agent.";
              const details = parseApprovalDetails(a);
              const risk = details?.risk_level || a.risk_level;
              return (
                <div
                  key={a.id}
                  className="card p-4 transition hover:border-primary-500/30 sm:p-5"
                >
                  <div className="mb-4 flex items-start gap-3">
                    <AlertTriangle
                      size={18}
                      className="mt-0.5 shrink-0 text-amber-500"
                    />
                    <div className="flex-1">
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <p className="text-sm font-medium text-ink">
                          {description}
                        </p>
                        {risk && (
                          <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium uppercase text-amber-700 dark:text-amber-300">
                            {risk}
                          </span>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center gap-3 text-xs text-ink-subtle">
                        <span className="flex items-center gap-1">
                          <Clock size={11} />
                          {relativeTime(a.created_at)}
                        </span>
                        {a.requested_by && (
                          <span>Requested by {a.requested_by}</span>
                        )}
                        {a.expires_at && (
                          <span className="text-amber-700 dark:text-amber-300">
                            Expires {relativeTime(a.expires_at)}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {details && (
                    <div className="mb-4 rounded-lg border border-surface-600 bg-surface-800/60 p-4">
                      <dl className="grid gap-4 sm:grid-cols-2">
                        <DetailRow
                          label="Repository"
                          value={details.repository}
                        />
                        <DetailRow
                          label="Workflow run"
                          value={details.workflow_run_id}
                        />
                        <DetailRow
                          label="Predicted failure"
                          value={details.predicted_failure}
                        />
                        <DetailRow
                          label="Workflow file"
                          value={details.workflow_path}
                        />
                        <DetailRow
                          label="Suggested fix"
                          value={details.suggested_fix}
                        />
                        <DetailRow
                          label="Workflow URL"
                          value={details.workflow_url}
                        />
                      </dl>
                      {details.proposed_file_changes &&
                        details.proposed_file_changes.length > 0 && (
                          <div className="mt-4">
                            <p className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">
                              Proposed file changes
                            </p>
                            <ul className="mt-2 space-y-1 text-sm text-ink-subtle">
                              {details.proposed_file_changes.map(
                                (change, index) => (
                                  <li key={`${a.id}-${index}`}>{change}</li>
                                ),
                              )}
                            </ul>
                          </div>
                        )}
                    </div>
                  )}

                  {canReviewOwn &&
                    canDecideRequest(a, false) &&
                    !canDecideRequest(a, true) && (
                      <p className="mb-3 text-xs text-ink-subtle">
                        An administrator must approve this action. You can
                        reject your request.
                      </p>
                    )}
                  {(canDecideRequest(a, true) ||
                    canDecideRequest(a, false)) && (
                    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
                      {canDecideRequest(a, true) && (
                        <button
                          onClick={() => decide(a, true)}
                          disabled={decidingId !== null}
                          className="btn-primary w-full sm:w-auto"
                        >
                          {decidingId === a.id ? (
                            <Loader2 size={14} className="animate-spin" />
                          ) : (
                            <CheckCircle size={14} />
                          )}
                          Approve
                        </button>
                      )}
                      {canDecideRequest(a, false) && (
                        <button
                          onClick={() => decide(a, false)}
                          disabled={decidingId !== null}
                          className="inline-flex w-full items-center justify-center gap-1.5 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm font-medium text-red-700 transition-colors hover:bg-red-500/15 disabled:cursor-not-allowed disabled:opacity-60 dark:text-red-300 sm:w-auto"
                        >
                          {decidingId === a.id ? (
                            <Loader2 size={14} className="animate-spin" />
                          ) : (
                            <XCircle size={14} />
                          )}
                          Reject
                        </button>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
