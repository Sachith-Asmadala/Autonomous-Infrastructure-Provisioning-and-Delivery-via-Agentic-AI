import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";
import { formatDistanceToNow } from "date-fns";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  CheckCircle2,
  ChevronRight,
  Clock3,
  GitBranch,
  GitPullRequest,
  History,
  Loader2,
  Network,
  RefreshCw,
  SearchCode,
  Server,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  TriangleAlert,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { getRoleDefinition, hasPermission } from "@/lib/rbac";
import {
  approvalService,
  executionService,
  healthService,
  workflowFailureService,
  type SystemStatus,
  type WorkflowFailure,
} from "@/services/api";
import { useAuthStore } from "@/store/authStore";
import type { User } from "@/types";

interface Approval {
  id: string;
  action?: string;
  summary?: string;
  description?: string;
  risk_level?: string;
  created_at?: string;
  status: string;
  requested_by?: string;
}
interface Execution {
  id: string;
  requested_by?: string;
  tool_name?: string;
  status: string;
  summary: string;
  started_at?: string;
}
interface DashboardData {
  status: SystemStatus | null;
  approvals: Approval[];
  failures: WorkflowFailure[];
  executions: Execution[];
}
type DataKey = keyof DashboardData;

const deliverySteps = [
  { icon: GitBranch, title: "Repository", detail: "Your source of truth" },
  { icon: Network, title: "AI diagnosis", detail: "Understand the failure" },
  {
    icon: ShieldCheck,
    title: "Human review",
    detail: "Approve with confidence",
  },
];

function relativeTime(value?: string) {
  if (!value || Number.isNaN(new Date(value).getTime()))
    return "Time unavailable";
  return formatDistanceToNow(new Date(value), { addSuffix: true });
}

function Panel({
  title,
  detail,
  to,
  children,
}: {
  title: string;
  detail: string;
  to?: string;
  children: ReactNode;
}) {
  return (
    <section className="card overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-surface-600 px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          <p className="mt-1 text-xs text-ink-subtle">{detail}</p>
        </div>
        {to && (
          <Link
            to={to}
            aria-label={`View all ${title.toLowerCase()}`}
            className="btn-ghost gap-1 px-2 text-xs"
          >
            View all <ArrowUpRight size={14} />
          </Link>
        )}
      </div>
      {children}
    </section>
  );
}

function Empty({
  icon: Icon,
  title,
  detail,
}: {
  icon: LucideIcon;
  title: string;
  detail: string;
}) {
  return (
    <div className="flex min-h-44 flex-col items-center justify-center px-6 py-8 text-center">
      <div className="mb-3 rounded-full bg-surface-700 p-3 text-ink-subtle">
        <Icon size={21} strokeWidth={1.5} />
      </div>
      <p className="text-sm font-medium text-ink">{title}</p>
      <p className="mt-1 max-w-xs text-xs leading-5 text-ink-subtle">
        {detail}
      </p>
    </div>
  );
}

function Loading() {
  return (
    <div role="status" className="space-y-3 p-5">
      <span className="sr-only">Loading dashboard data</span>
      {[1, 2, 3].map((n) => (
        <div key={n} className="h-10 animate-pulse rounded-lg bg-surface-700" />
      ))}
    </div>
  );
}

const quickActions = [
  {
    title: "Diagnose a failure",
    detail: "Turn a failed build log into a clear next step.",
    to: "/diagnosis#diagnose",
    icon: SearchCode,
    permission: "failures:predict",
    color: "text-primary-600 dark:text-primary-300 bg-primary-500/10",
    label: "01 / DIAGNOSE",
  },
  {
    title: "Generate a workflow",
    detail: "Build a GitHub Actions workflow for your stack.",
    to: "/diagnosis#workflow",
    icon: Workflow,
    permission: "cicd:generate",
    color: "text-blue-600 dark:text-blue-300 bg-blue-500/10",
    label: "02 / AUTOMATE",
  },
  {
    title: "Connect a repository",
    detail: "Scan your code and prepare a reviewed pull request.",
    to: "/repository-setup",
    icon: GitBranch,
    permission: "repositories:write",
    color: "text-violet-600 dark:text-violet-300 bg-violet-500/10",
    label: "03 / DELIVER",
  },
];

export default function DashboardPage() {
  const user = useAuthStore((state) => state.user);
  return <DashboardContent key={`${user?.id}:${user?.role}`} user={user} />;
}

function DashboardContent({ user }: { user: User | null }) {
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState<DataKey[]>([]);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [data, setData] = useState<DashboardData>({
    status: null,
    approvals: [],
    failures: [],
    executions: [],
  });
  const requestId = useRef(0);
  const isAdmin = user?.role === "admin";
  const canReadApprovals = hasPermission(user?.role, "approvals:read");
  const canReadFailures =
    isAdmin && hasPermission(user?.role, "workflow_failures:read");
  const canReadExecutions = hasPermission(user?.role, "executions:read");
  const can = (permission: string) => hasPermission(user?.role, permission);

  const loadDashboard = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    const [status, approvals, failures, executions] = await Promise.allSettled([
      isAdmin ? healthService.status() : Promise.resolve(null),
      canReadApprovals
        ? approvalService.list(isAdmin ? "all" : "mine")
        : Promise.resolve([]),
      canReadFailures ? workflowFailureService.list(5) : Promise.resolve([]),
      canReadExecutions
        ? executionService.list({ limit: 5, days: 7 })
        : Promise.resolve([]),
    ]);
    if (id !== requestId.current) return;
    const failed: DataKey[] = [];
    if (status.status === "rejected") failed.push("status");
    if (approvals.status === "rejected" || !Array.isArray(approvals.value))
      failed.push("approvals");
    if (failures.status === "rejected" || !Array.isArray(failures.value))
      failed.push("failures");
    if (executions.status === "rejected" || !Array.isArray(executions.value))
      failed.push("executions");
    setUnavailable(failed);
    setData({
      status: status.status === "fulfilled" ? status.value : null,
      approvals:
        approvals.status === "fulfilled" && Array.isArray(approvals.value)
          ? approvals.value
          : [],
      failures:
        failures.status === "fulfilled" && Array.isArray(failures.value)
          ? failures.value
          : [],
      executions:
        executions.status === "fulfilled" && Array.isArray(executions.value)
          ? executions.value
          : [],
    });
    setUpdated(new Date());
    setLoading(false);
  }, [canReadApprovals, canReadFailures, canReadExecutions, isAdmin, user?.id]);

  useEffect(() => {
    void loadDashboard();
    return () => {
      requestId.current++;
    };
  }, [loadDashboard]);
  const services = data.status
    ? [
        {
          name: "Backend API",
          detail: "Application services",
          ok: data.status.backend_api.status === "ok",
          message: data.status.backend_api.message,
          icon: Server,
        },
        {
          name: "GitHub",
          detail: "Repository integration",
          ok: data.status.github.configured,
          message: data.status.github.message,
          icon: GitPullRequest,
        },
        {
          name: "Failure classifier",
          detail: "ML diagnosis model",
          ok: data.status.ml_model.available,
          message: data.status.ml_model.message,
          icon: Network,
        },
        {
          name: "Docker",
          detail: "Container runtime",
          ok: data.status.docker.available,
          message: data.status.docker.message,
          icon: TerminalSquare,
        },
      ]
    : [];
  const ready = services.filter((service) => service.ok).length;
  const value = (key: DataKey, allowed: boolean, count: number | string) =>
    !allowed ? "—" : loading ? "…" : unavailable.includes(key) ? "—" : count;
  const metrics = [
    {
      label: "Service readiness",
      value: value("status", true, `${ready} / 4`),
      detail: unavailable.includes("status")
        ? "Status unavailable"
        : "Connected core services",
      icon: Activity,
      accent: "text-primary-600 dark:text-primary-300",
    },
    {
      label: "Pending approvals",
      value: value("approvals", canReadApprovals, data.approvals.length),
      detail: !canReadApprovals
        ? "Not available for your role"
        : unavailable.includes("approvals")
          ? "Queue unavailable"
          : "Waiting for human review",
      icon: ShieldCheck,
      accent: "text-amber-600 dark:text-amber-300",
    },
    {
      label: "Recent failures",
      value: value("failures", canReadFailures, data.failures.length),
      detail: !canReadFailures
        ? "Not available for your role"
        : unavailable.includes("failures")
          ? "Records unavailable"
          : "Latest 5 workflow failure records",
      icon: TriangleAlert,
      accent: "text-rose-500 dark:text-rose-300",
    },
    {
      label: "Recent activity",
      value: value("executions", canReadExecutions, data.executions.length),
      detail: !canReadExecutions
        ? "Not available for your role"
        : unavailable.includes("executions")
          ? "Audit unavailable"
          : "Latest 5 actions · past 7 days",
      icon: History,
      accent: "text-blue-600 dark:text-blue-300",
    },
  ];
  const unavailablePanel = (key: DataKey) =>
    unavailable.includes(key) ? (
      <Empty
        icon={TriangleAlert}
        title="Unable to load this section"
        detail="Refresh to try again. Other available data is shown normally."
      />
    ) : null;

  if (!isAdmin) {
    const role = getRoleDefinition(user?.role);
    const ownMetrics = [
      {
        label: "Your recent actions",
        count: data.executions.length,
        key: "executions" as DataKey,
        detail: "Latest 5 actions · past 7 days",
        icon: History,
      },
      {
        label: "Completed actions",
        count: data.executions.filter((item) =>
          ["completed", "success"].includes(item.status),
        ).length,
        key: "executions" as DataKey,
        detail: "Within your recent activity",
        icon: CheckCircle2,
      },
      {
        label: "Failed actions",
        count: data.executions.filter((item) => item.status === "failed")
          .length,
        key: "executions" as DataKey,
        detail: "Within your recent activity",
        icon: TriangleAlert,
      },
      {
        label: "Your pending requests",
        count: data.approvals.length,
        key: "approvals" as DataKey,
        detail: "Your requests waiting for review",
        icon: ShieldCheck,
      },
    ];
    return (
      <div className="h-full overflow-y-auto bg-surface-900">
        <div className="mx-auto max-w-[1440px] space-y-6 px-4 py-6 md:px-8 md:py-8">
          <header className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="mb-2 text-xs font-medium text-primary-700 dark:text-primary-300">
                {role.label} workspace
              </p>
              <h1 className="text-2xl font-semibold tracking-tight text-ink">
                Your dashboard
              </h1>
              <p className="mt-2 text-sm text-ink-subtle">
                Welcome, {user?.username}. Your actions, requests, and next
                steps are here.
              </p>
            </div>
            <button
              onClick={loadDashboard}
              disabled={loading}
              className="btn-secondary"
            >
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
              Refresh
            </button>
          </header>
          <section className="card flex flex-wrap items-center justify-between gap-4 p-5">
            <div>
              <h2 className="text-sm font-semibold text-ink">
                Your workspace, your activity
              </h2>
              <p className="mt-1 text-xs leading-5 text-ink-subtle">
                This dashboard and your audit log show only actions recorded
                under your account. {role.headline}.
              </p>
            </div>
            <Link to="/chat" className="btn-primary">
              Open agent chat <ArrowRight size={14} />
            </Link>
          </section>
          {unavailable.length > 0 && (
            <div
              role="alert"
              className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-800 dark:text-amber-200"
            >
              Some of your activity could not be loaded. Refresh to try again;
              unavailable counts are shown as a dash.
            </div>
          )}
          <section
            aria-label="Your activity metrics"
            className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"
          >
            {ownMetrics.map(({ label, count, key, detail, icon: Icon }) => (
              <div key={label} className="card p-5">
                <div className="flex items-center justify-between">
                  <h2 className="text-xs font-medium text-ink-subtle">
                    {label}
                  </h2>
                  <Icon
                    size={17}
                    className="text-primary-600 dark:text-primary-300"
                  />
                </div>
                <p className="mt-3 text-3xl font-semibold text-ink">
                  {value(
                    key,
                    key === "approvals" ? canReadApprovals : canReadExecutions,
                    count,
                  )}
                </p>
                <p className="mt-2 text-[11px] text-ink-subtle">
                  {unavailable.includes(key) ? "Data unavailable" : detail}
                </p>
              </div>
            ))}
          </section>
          <section
            aria-label="Available delivery tasks"
            className="grid gap-3 md:grid-cols-3"
          >
            {quickActions
              .filter((action) => can(action.permission))
              .map(({ title, detail, to, icon: Icon, color }) => (
                <Link key={title} to={to} className="action-card">
                  <span className={`mb-3 inline-flex rounded-lg p-2 ${color}`}>
                    <Icon size={19} />
                  </span>
                  <h2 className="text-sm font-semibold text-ink">{title}</h2>
                  <p className="mt-1 text-xs leading-5 text-ink-subtle">
                    {detail}
                  </p>
                </Link>
              ))}
          </section>
          <div className="grid items-start gap-5 xl:grid-cols-2">
            <Panel
              title="Your recent activity"
              detail="Latest 5 actions recorded under your account · last 7 days"
              to="/executions"
            >
              {loading ? (
                <Loading />
              ) : (
                unavailablePanel("executions") ||
                (data.executions.length ? (
                  <div className="divide-y divide-surface-600">
                    {data.executions.map((execution) => (
                      <Link
                        key={execution.id}
                        to="/executions"
                        className="flex items-start gap-3 px-5 py-4 hover:bg-surface-700/50"
                      >
                        <History
                          size={17}
                          className="mt-1 shrink-0 text-ink-subtle"
                        />
                        <div className="min-w-0 flex-1">
                          <p className="break-words text-sm font-medium text-ink">
                            {execution.summary ||
                              execution.tool_name ||
                              "Your action"}
                          </p>
                          <p className="mt-1 text-xs text-ink-subtle">
                            {execution.tool_name || "Agent"} ·{" "}
                            {relativeTime(execution.started_at)}
                          </p>
                        </div>
                        <span
                          className={
                            execution.status === "failed"
                              ? "badge-error"
                              : "badge-info"
                          }
                        >
                          {execution.status}
                        </span>
                      </Link>
                    ))}
                  </div>
                ) : (
                  <Empty
                    icon={History}
                    title="No activity recorded yet"
                    detail="Ask the agent a question or use an available delivery tool to begin."
                  />
                ))
              )}
            </Panel>
            <Panel
              title="Your pending requests"
              detail="Actions you requested that are waiting for approval"
              to="/approvals"
            >
              {loading ? (
                <Loading />
              ) : (
                unavailablePanel("approvals") ||
                (data.approvals.length ? (
                  <div className="divide-y divide-surface-600">
                    {data.approvals.slice(0, 5).map((approval) => (
                      <Link
                        key={approval.id}
                        to="/approvals"
                        className="block px-5 py-4 hover:bg-surface-700/50"
                      >
                        <p className="text-sm font-medium text-ink">
                          {approval.summary ||
                            approval.action ||
                            "Your approval request"}
                        </p>
                        <p className="mt-1 text-xs text-ink-subtle">
                          {relativeTime(approval.created_at)} ·{" "}
                          {approval.status}
                        </p>
                      </Link>
                    ))}
                  </div>
                ) : (
                  <Empty
                    icon={ShieldCheck}
                    title="No pending requests"
                    detail="Your high-risk action requests will appear here while awaiting review."
                  />
                ))
              )}
            </Panel>
          </div>
          {(can("approvals:decide") || can("approvals:decide:own")) && (
            <section className="card flex flex-wrap items-center justify-between gap-4 p-5">
              <div>
                <h2 className="text-sm font-semibold text-ink">
                  {can("approvals:decide")
                    ? "Review requests as an admin"
                    : "Review your own work"}
                </h2>
                <p className="mt-1 text-xs text-ink-subtle">
                  {can("approvals:decide")
                    ? "Your approval role lets you review the shared queue on the approvals page."
                    : "Review and decide your own CI/CD requests before they execute."}
                </p>
              </div>
              <Link to="/approvals" className="btn-secondary">
                Open review queue <ArrowUpRight size={14} />
              </Link>
            </section>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto bg-surface-900">
      <div className="mx-auto max-w-[1440px] space-y-7 px-4 py-6 md:px-8 md:py-8">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="mb-1.5 flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.15em] text-ink-subtle">
              <span className="h-1.5 w-1.5 rounded-full bg-primary-500" />
              Your workspace at a glance
            </div>
            <h1 className="text-2xl font-semibold tracking-tight text-ink md:text-[28px]">
              Operations overview
            </h1>
            <p className="mt-1.5 text-sm text-ink-subtle">
              A clearer path from failed build to successful delivery.
            </p>
          </div>
          <button
            onClick={loadDashboard}
            disabled={loading}
            className="btn-secondary"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
        </header>

        <section className="overview-hero relative overflow-hidden rounded-2xl px-6 py-7 text-white md:px-8">
          <div className="relative z-10 max-w-xl">
            <p className="mb-3 flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.18em] text-emerald-300">
              <Sparkles size={14} />
              AI-assisted delivery
            </p>
            <h2 className="text-2xl font-medium tracking-tight md:text-3xl">
              Less firefighting.
              <br />
              More moving forward.
            </h2>
            <p className="mt-3 max-w-md text-sm leading-6 text-slate-300">
              Diagnose CI/CD failures, build workflows, and keep every change
              under your control.
            </p>
            <Link
              to="/chat"
              className="mt-5 inline-flex items-center gap-3 rounded-lg bg-emerald-400 px-4 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-emerald-300"
            >
              Open agent chat <ArrowRight size={16} />
            </Link>
          </div>
          <div
            aria-hidden="true"
            className="hero-workflow absolute right-12 top-1/2 hidden w-64 -translate-y-1/2 space-y-3 xl:block"
          >
            {deliverySteps.map(({ icon: StepIcon, title, detail }, index) => {
              return (
                <div
                  key={String(title)}
                  className="flex items-center gap-3 rounded-xl border border-white/15 bg-white/[0.06] p-3 backdrop-blur-sm"
                  style={{
                    transform: `translateX(${index === 1 ? -24 : 0}px)`,
                  }}
                >
                  <span className="rounded-lg bg-emerald-400/10 p-2 text-emerald-300">
                    <StepIcon size={18} />
                  </span>
                  <div>
                    <p className="text-xs font-medium text-white">
                      {String(title)}
                    </p>
                    <p className="mt-1 text-[10px] text-slate-400">
                      {String(detail)}
                    </p>
                  </div>
                  <CheckCircle2
                    size={15}
                    className="ml-auto text-emerald-400/70"
                  />
                </div>
              );
            })}
          </div>
        </section>

        <section
          aria-label="Quick actions"
          className="grid gap-3 md:grid-cols-3"
        >
          {quickActions
            .filter((action) => can(action.permission))
            .map(({ title, detail, to, icon: Icon, color, label }) => (
              <Link key={title} to={to} className="action-card group">
                <div className="mb-4 flex items-center justify-between">
                  <span className={`rounded-lg p-2.5 ${color}`}>
                    <Icon size={20} strokeWidth={1.7} />
                  </span>
                  <ArrowUpRight
                    size={16}
                    className="text-ink-faint transition group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-primary-600"
                  />
                </div>
                <p className="mb-2 text-[9px] font-semibold tracking-[0.13em] text-ink-subtle">
                  {label}
                </p>
                <h2 className="text-sm font-semibold text-ink">{title}</h2>
                <p className="mt-1.5 text-xs leading-5 text-ink-subtle">
                  {detail}
                </p>
              </Link>
            ))}
        </section>

        {unavailable.length > 0 && (
          <div
            role="alert"
            className="flex items-start gap-3 rounded-lg border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200"
          >
            <TriangleAlert size={18} className="mt-0.5 shrink-0" />
            <div>
              <p className="font-medium">Some workspace data is unavailable</p>
              <p className="mt-1 text-xs">
                Check your connection or backend settings, then refresh.
                Unavailable counts are shown as a dash.
              </p>
              <Link
                to="/settings"
                className="mt-2 inline-flex items-center gap-1 text-xs font-semibold underline underline-offset-4"
              >
                Open settings <ChevronRight size={12} />
              </Link>
            </div>
          </div>
        )}

        <section
          aria-label="Workspace metrics"
          className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"
        >
          {metrics.map(
            ({ label, value: count, detail, icon: Icon, accent }) => (
              <div key={label} className="card p-5">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium text-ink-subtle">{label}</p>
                  <Icon size={17} strokeWidth={1.7} className={accent} />
                </div>
                <p className="mt-3 text-3xl font-semibold tracking-tight text-ink">
                  {count}
                </p>
                <p className="mt-2 text-[11px] text-ink-subtle">{detail}</p>
              </div>
            ),
          )}
        </section>

        <div className="grid items-start gap-5 xl:grid-cols-[1.35fr_1fr]">
          <Panel
            title="Service connections"
            detail="The services that power your delivery workflow"
            to="/settings"
          >
            {loading ? (
              <Loading />
            ) : (
              unavailablePanel("status") || (
                <div className="divide-y divide-surface-600">
                  {services.map(({ name, detail, ok, message, icon: Icon }) => (
                    <div
                      key={name}
                      className="flex items-center gap-3 px-5 py-4"
                    >
                      <span className="rounded-lg border border-surface-600 bg-surface-900 p-2 text-ink-muted">
                        <Icon size={17} strokeWidth={1.7} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-ink">{name}</p>
                        <p className="mt-0.5 text-[11px] leading-5 text-ink-subtle">
                          {detail}
                          {!ok && message ? ` · ${message}` : ""}
                        </p>
                      </div>
                      <span
                        title={message}
                        className={ok ? "badge-success" : "badge-warning"}
                      >
                        <span
                          className={`mr-1.5 h-1.5 w-1.5 rounded-full ${ok ? "bg-primary-500" : "bg-amber-500"}`}
                        />
                        {ok ? "Ready" : "Needs setup"}
                      </span>
                    </div>
                  ))}
                </div>
              )
            )}
          </Panel>
          <Panel
            title="Approval queue"
            detail="Your checkpoint before changes are made"
            to={canReadApprovals ? "/approvals" : undefined}
          >
            {!canReadApprovals ? (
              <Empty
                icon={ShieldCheck}
                title="Managed by your admin"
                detail="Your role cannot view the approval queue."
              />
            ) : loading ? (
              <Loading />
            ) : (
              unavailablePanel("approvals") ||
              (data.approvals.length ? (
                <div className="divide-y divide-surface-600">
                  {data.approvals.slice(0, 3).map((approval) => (
                    <Link
                      key={approval.id}
                      to="/approvals"
                      className="flex items-start gap-3 px-5 py-4 transition hover:bg-surface-700/50"
                    >
                      <span className="mt-0.5 rounded-lg bg-amber-500/10 p-2 text-amber-600">
                        <ShieldCheck size={16} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="line-clamp-2 text-sm font-medium text-ink">
                          {approval.summary ||
                            approval.description ||
                            approval.action ||
                            "Action requires approval"}
                        </p>
                        <p className="mt-1 text-xs text-ink-subtle">
                          Requested by: {approval.requested_by || "Unknown"} ·{" "}
                          {relativeTime(approval.created_at)}
                        </p>
                      </div>
                      <ChevronRight
                        size={15}
                        className="mt-2 shrink-0 text-ink-faint"
                      />
                    </Link>
                  ))}
                </div>
              ) : (
                <Empty
                  icon={ShieldCheck}
                  title="All clear for now"
                  detail="Actions that need your approval will appear here. You stay in control of every high-risk change."
                />
              ))
            )}
            <div className="flex items-center gap-2 border-t border-surface-600 bg-surface-900/60 px-5 py-3 text-[11px] text-ink-subtle">
              <ShieldCheck
                size={13}
                className="text-primary-600 dark:text-primary-300"
              />
              Changes require review before execution.
            </div>
          </Panel>
        </div>

        <div className="grid items-start gap-5 xl:grid-cols-2">
          <Panel
            title="Workflow failures"
            detail="Recent runs received from GitHub Actions"
            to={canReadFailures ? "/workflow-failures" : undefined}
          >
            {!canReadFailures ? (
              <Empty
                icon={Workflow}
                title="Workflow records are restricted"
                detail="Your role does not have access to these records."
              />
            ) : loading ? (
              <Loading />
            ) : (
              unavailablePanel("failures") ||
              (data.failures.length ? (
                <div className="divide-y divide-surface-600">
                  {data.failures.slice(0, 4).map((failure) => (
                    <Link
                      key={failure.id}
                      to="/workflow-failures"
                      className="flex items-center gap-3 px-5 py-4 hover:bg-surface-700/50"
                    >
                      <span className="rounded-lg bg-rose-500/10 p-2 text-rose-500">
                        <GitBranch size={16} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-ink">
                          {failure.repo_full_name}
                        </p>
                        <p className="mt-1 truncate text-xs text-ink-subtle">
                          {failure.predicted_label || "Awaiting diagnosis"} ·{" "}
                          {relativeTime(failure.created_at)}
                        </p>
                      </div>
                      <span className="badge-info">
                        {failure.status.replace(/_/g, " ")}
                      </span>
                    </Link>
                  ))}
                </div>
              ) : (
                <Empty
                  icon={CheckCircle2}
                  title="No failure records yet"
                  detail="Failed workflow runs appear here after a GitHub webhook is received."
                />
              ))
            )}
          </Panel>
          <Panel
            title="Recent activity"
            detail="All members and system actions · last 7 days"
            to={canReadExecutions ? "/executions" : undefined}
          >
            {!canReadExecutions ? (
              <Empty
                icon={History}
                title="Activity is restricted"
                detail="Your role does not have access to the audit log."
              />
            ) : loading ? (
              <Loading />
            ) : (
              unavailablePanel("executions") ||
              (data.executions.length ? (
                <div className="divide-y divide-surface-600">
                  {data.executions.map((execution) => (
                    <Link
                      key={execution.id}
                      to="/executions"
                      className="flex items-center gap-3 px-5 py-4 hover:bg-surface-700/50"
                    >
                      <span className="rounded-lg bg-surface-700 p-2 text-ink-subtle">
                        {execution.status === "running" ? (
                          <Loader2 size={16} className="animate-spin" />
                        ) : (
                          <Clock3 size={16} />
                        )}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-ink">
                          {execution.summary ||
                            execution.tool_name ||
                            "Agent action"}
                        </p>
                        <p className="mt-1 text-xs text-ink-subtle">
                          Actor: {execution.requested_by || "Unknown"} ·{" "}
                          {relativeTime(execution.started_at)}
                        </p>
                      </div>
                      <span
                        className={
                          execution.status === "failed"
                            ? "badge-error"
                            : "badge-info"
                        }
                      >
                        {execution.status}
                      </span>
                    </Link>
                  ))}
                </div>
              ) : (
                <Empty
                  icon={History}
                  title="Your activity starts here"
                  detail="Run a diagnosis or ask your agent a question to start building your audit trail."
                />
              ))
            )}
          </Panel>
        </div>
        <section className="rounded-xl border border-dashed border-surface-600 px-5 py-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-xs font-semibold text-ink-muted">
              How your request moves through the system
            </h2>
            {can("agents:orchestrate") && (
              <Link
                to="/multi-agent"
                className="inline-flex items-center gap-1 text-xs text-primary-700 dark:text-primary-300"
              >
                Explore agents <ArrowUpRight size={12} />
              </Link>
            )}
          </div>
          <ol className="flex flex-wrap items-center gap-x-3 gap-y-2">
            {[
              "Your request",
              "Orchestration agent",
              "One specialized agent",
              "Tool or service",
              "Structured response",
            ].map((step, index) => (
              <li
                key={step}
                className="flex items-center gap-2 text-[11px] text-ink-subtle"
              >
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-surface-700 text-[10px] font-medium">
                  {index + 1}
                </span>
                {step}
                {index < 4 && (
                  <ChevronRight size={12} className="ml-1 text-ink-faint" />
                )}
              </li>
            ))}
          </ol>
        </section>
        <footer className="flex flex-wrap items-center justify-between gap-2 pb-2 text-[11px] text-ink-subtle">
          <span className="flex items-center gap-1.5">
            <ShieldCheck size={13} />
            AI assistance. Human control.
          </span>
          <span aria-live="polite">
            {loading
              ? "Checking workspace…"
              : updated
                ? `Last checked ${updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
                : "Not checked yet"}
          </span>
        </footer>
      </div>
    </div>
  );
}
