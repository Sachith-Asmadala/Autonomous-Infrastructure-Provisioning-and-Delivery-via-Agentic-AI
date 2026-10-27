import { getDebugHint, getUserFriendlyError } from "@/lib/errorMessages";
import { executionService } from "@/services/api";
import { useAuthStore } from "@/store/authStore";
import type { User } from "@/types";
import { formatDistanceToNow } from "date-fns";
import {
  Activity,
  AlertCircle,
  CheckCircle,
  Clock,
  Loader,
  RefreshCw,
  Search,
  X,
  XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";

interface Execution {
  id: string;
  requested_by: string;
  tool_name: string;
  status: string;
  source: string;
  summary: string;
  details?: string;
  started_at?: string;
  completed_at?: string;
  approval_decided_by?: string | null;
  approval_status?: string | null;
}

interface Filters {
  tool: string | null;
  status: string | null;
  actor: string | null;
  days: number;
}

const TOOL_OPTIONS = [
  "failure_prediction_model",
  "github_create_workflow_pr",
  "github_create_fix_pr",
  "github_workflow_pr",
  "github_fix_pr",
  "repository_analyzer",
  "workflow_generator",
  "fix_recommendation",
  "approval_decision",
  "github_log_downloader",
];

const STATUS_OPTIONS = ["completed", "failed", "pending", "cancelled"];

const statusIcon = (status: string) => {
  switch (status) {
    case "success":
    case "completed":
      return (
        <CheckCircle
          size={14}
          className="text-primary-600 dark:text-primary-300"
        />
      );
    case "failed":
      return <XCircle size={14} className="text-red-500 dark:text-red-300" />;
    case "running":
      return (
        <Loader
          size={14}
          className="animate-spin text-blue-500 dark:text-blue-300"
        />
      );
    default:
      return <Clock size={14} className="text-ink-subtle" />;
  }
};

const statusBadge = (status: string) => {
  const classes: Record<string, string> = {
    completed: "badge-success",
    success: "badge-success",
    running: "badge-info",
    failed: "badge-error",
    cancelled: "badge-warning",
  };
  const cls = classes[status] || "badge-info";
  return <span className={cls}>{status}</span>;
};

const relativeTime = (value?: string) => {
  if (!value) return "time unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "time unknown";
  return formatDistanceToNow(date, { addSuffix: true });
};

export default function ExecutionsPage() {
  const user = useAuthStore((state) => state.user);
  return <ExecutionsContent key={`${user?.id}:${user?.role}`} user={user} />;
}

function ExecutionsContent({ user }: { user: User | null }) {
  const isAdmin = user?.role === "admin";
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [actorInput, setActorInput] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filters, setFilters] = useState<Filters>({
    tool: null,
    status: null,
    actor: null,
    days: 7,
  });

  useEffect(() => {
    let active = true;
    const fetchExecutions = async () => {
      setLoading(true);
      setError("");
      setExecutions([]);
      try {
        const data = await executionService.list({
          tool: filters.tool,
          status: filters.status,
          actor: isAdmin ? filters.actor : null,
          days: filters.days,
        });
        if (active) setExecutions(Array.isArray(data) ? data : []);
      } catch (err: unknown) {
        if (active) setError(getUserFriendlyError(err));
      } finally {
        if (active) setLoading(false);
      }
    };
    void fetchExecutions();
    return () => {
      active = false;
    };
  }, [filters, isAdmin, user?.id, refresh]);

  const handleClearFilters = () => {
    setFilters({ tool: null, status: null, actor: null, days: 7 });
    setActorInput("");
  };

  const hasActiveFilters = filters.tool || filters.status || filters.actor;

  return (
    <div className="flex h-full flex-col bg-surface-900">
      <div className="workspace-page-header shrink-0">
        <div className="mb-4 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-blue-500/30 bg-blue-500/10">
            <Activity size={19} className="text-blue-600 dark:text-blue-300" />
          </div>
          <div>
            <h1 className="text-base font-semibold text-ink">
              {isAdmin ? "Team audit log" : "Your audit log"}
            </h1>
            <p className="text-xs text-ink-subtle">
              {isAdmin
                ? "All members and system actions, with the account responsible for each record"
                : "Only actions recorded under your account are shown here"}
            </p>
          </div>
        </div>

        {/* Filters */}
        <div className="grid gap-3 sm:grid-cols-2 xl:flex xl:flex-wrap xl:items-center">
          <select
            aria-label="Filter by tool"
            value={filters.tool || ""}
            onChange={(e) =>
              setFilters({ ...filters, tool: e.target.value || null })
            }
            className="input-field min-h-10 px-3 py-2 xl:w-auto"
          >
            <option value="">All Tools</option>
            {TOOL_OPTIONS.map((tool) => (
              <option key={tool} value={tool}>
                {tool}
              </option>
            ))}
          </select>

          <select
            aria-label="Filter by status"
            value={filters.status || ""}
            onChange={(e) =>
              setFilters({ ...filters, status: e.target.value || null })
            }
            className="input-field min-h-10 px-3 py-2 xl:w-auto"
          >
            <option value="">All Status</option>
            {STATUS_OPTIONS.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>

          <select
            aria-label="Filter by time period"
            value={filters.days.toString()}
            onChange={(e) =>
              setFilters({ ...filters, days: parseInt(e.target.value) })
            }
            className="input-field min-h-10 px-3 py-2 xl:w-auto"
          >
            <option value="1">Last 24 hours</option>
            <option value="7">Last 7 days</option>
            <option value="30">Last 30 days</option>
          </select>

          {isAdmin && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                setFilters({ ...filters, actor: actorInput.trim() || null });
              }}
              className="flex gap-2"
            >
              <input
                aria-label="Actor username"
                placeholder="Actor username (exact)"
                value={actorInput}
                onChange={(event) => setActorInput(event.target.value)}
                className="input-field min-h-10 min-w-0 px-3 py-2"
              />
              <button
                type="submit"
                className="btn-secondary"
                aria-label="Filter by actor"
              >
                <Search size={15} />
              </button>
            </form>
          )}
          <button
            type="button"
            onClick={() => setRefresh((value) => value + 1)}
            disabled={loading}
            className="btn-secondary"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>

          {hasActiveFilters && (
            <button
              onClick={handleClearFilters}
              className="btn-ghost min-h-10 border border-surface-600"
            >
              <X size={14} />
              Clear
            </button>
          )}
        </div>
      </div>

      <div className="workspace-page-body min-h-0 flex-1 overflow-y-auto py-5">
        {loading ? (
          <div className="flex h-32 items-center justify-center">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
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
        ) : executions.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <div className="mb-4 rounded-3xl border border-surface-600 bg-surface-800 p-4">
              <Clock size={40} className="text-ink-subtle" />
            </div>
            <p className="font-medium text-ink">No executions found</p>
            <p className="mt-1 text-sm text-ink-subtle">
              Try adjusting your filters or check back later.
            </p>
          </div>
        ) : (
          <div className="mx-auto max-w-4xl space-y-2">
            {executions.map((ex) => (
              <div
                key={ex.id}
                className="card flex flex-col gap-3 px-4 py-3 transition-colors hover:border-primary-500/30"
              >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
                  <div className="shrink-0">{statusIcon(ex.status)}</div>
                  <div className="min-w-0 flex-1">
                    <p className="break-words text-sm font-medium text-ink sm:truncate">
                      {ex.summary}
                    </p>
                    <p className="mt-0.5 flex flex-wrap gap-x-2 gap-y-1 text-xs text-ink-subtle">
                      {ex.source && (
                        <span className="break-all font-mono text-primary-700 dark:text-primary-300">
                          {ex.source}
                        </span>
                      )}
                      {ex.tool_name && (
                        <span className="break-all font-mono text-ink-subtle">
                          {ex.tool_name}
                        </span>
                      )}
                      <span>{relativeTime(ex.started_at)}</span>
                    </p>
                  </div>
                  <div className="shrink-0 sm:self-center">
                    {statusBadge(ex.status)}
                  </div>
                </div>
                {isAdmin && ex.requested_by && (
                  <p className="text-xs text-ink-subtle sm:ml-8">
                    Actor / requester:{" "}
                    <span className="font-medium text-ink">
                      {ex.requested_by}
                    </span>
                  </p>
                )}
                {ex.approval_decided_by && (
                  <p className="text-xs text-ink-subtle sm:ml-8">
                    Approval {ex.approval_status}:{" "}
                    <span className="font-medium text-ink">
                      {ex.approval_decided_by}
                    </span>
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
