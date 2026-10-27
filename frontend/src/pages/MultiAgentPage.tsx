import { getDebugHint, getUserFriendlyError } from "@/lib/errorMessages";
import {
  agentService,
  type AgentOrchestrationResult,
  type AgentTraceStep,
} from "@/services/api";
import {
  AlertCircle,
  Bot,
  Braces,
  CheckCircle2,
  Circle,
  Loader2,
  Network,
  Play,
  Route,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { useMemo, useState } from "react";

const demoContexts = {
  containers: "{}",
  reactWorkflow: JSON.stringify(
    {
      files: [
        "package.json",
        "package-lock.json",
        "src/App.jsx",
        "vite.config.js",
      ],
    },
    null,
    2,
  ),
  npmLog: JSON.stringify(
    {
      log_text:
        'npm ERR! Missing script: "test"\nnpm ERR! To see a list of scripts, run:\nnpm ERR!   npm run',
    },
    null,
    2,
  ),
  repoScan: JSON.stringify(
    {
      repo_full_name: "owner/repo",
    },
    null,
    2,
  ),
};

const quickDemos = [
  {
    label: "Show running containers",
    message: "show running containers",
    context: demoContexts.containers,
  },
  {
    label: "Generate CI workflow for React project",
    message: "generate CI workflow",
    context: demoContexts.reactWorkflow,
  },
  {
    label: "Analyze npm missing test script log",
    message: "analyze this log",
    context: demoContexts.npmLog,
  },
  {
    label: "Scan GitHub repository",
    message: "scan repository",
    context: demoContexts.repoScan,
  },
];

function formatJson(value: unknown) {
  return JSON.stringify(value, null, 2);
}

function errorMessage(err: unknown) {
  return getUserFriendlyError(err);
}

function riskBadgeClass(risk: string) {
  if (risk === "high") return "badge-error";
  if (risk === "medium") return "badge-warning";
  return "badge-success";
}

function ResultPanel({ result }: { result: AgentOrchestrationResult }) {
  const toolCalled =
    typeof result.metadata.tool_called === "string"
      ? result.metadata.tool_called
      : typeof result.metadata.proposed_tool_call === "string"
        ? result.metadata.proposed_tool_call
        : "Not reported";

  return (
    <section className="card overflow-hidden">
      <div className="border-b border-surface-600 px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            {result.success ? (
              <CheckCircle2
                size={18}
                className="text-primary-600 dark:text-primary-300"
              />
            ) : (
              <ShieldAlert
                size={18}
                className="text-amber-600 dark:text-amber-300"
              />
            )}
            <h2 className="text-sm font-semibold text-ink">Agent Result</h2>
          </div>
          <span className={riskBadgeClass(result.risk_level)}>
            {result.risk_level}
          </span>
        </div>
      </div>

      <div className="space-y-4 p-5">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-2xl border border-surface-600 bg-surface-900/70 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
              Selected Agent
            </p>
            <p className="mt-2 break-words font-mono text-sm font-semibold text-ink">
              {result.selected_agent}
            </p>
          </div>
          <div className="rounded-2xl border border-surface-600 bg-surface-900/70 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
              Intent
            </p>
            <p className="mt-2 break-words font-mono text-sm font-semibold text-ink">
              {result.intent}
            </p>
          </div>
          <div className="rounded-2xl border border-surface-600 bg-surface-900/70 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
              Success
            </p>
            <p className="mt-2 text-sm font-semibold text-ink">
              {result.success ? "true" : "false"}
            </p>
          </div>
          <div className="rounded-2xl border border-surface-600 bg-surface-900/70 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
              Tool Called
            </p>
            <p className="mt-2 break-words font-mono text-sm font-semibold text-ink">
              {toolCalled}
            </p>
          </div>
        </div>

        <div className="rounded-2xl border border-surface-600 bg-surface-900/70 p-4">
          <p className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
            Result
          </p>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-ink">
            {result.result}
          </p>
        </div>

        <AgentTracePanel traceSteps={result.metadata.trace_steps} />

        <details className="rounded-2xl border border-surface-600 bg-surface-950">
          <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-ink">
            Metadata JSON
          </summary>
          <pre className="max-h-96 max-w-full overflow-auto border-t border-surface-600 p-4 text-xs leading-5 text-ink">
            <code>{formatJson(result.metadata)}</code>
          </pre>
        </details>
      </div>
    </section>
  );
}

function traceStatusClass(status: string) {
  if (status === "completed") return "badge-success";
  if (status === "pending") return "badge-warning";
  if (status === "failed") return "badge-error";
  return "badge-info";
}

function TraceDetails({ details }: { details: AgentTraceStep["details"] }) {
  if (!details) return null;
  if (typeof details === "string") {
    return <p className="mt-1 text-xs text-ink-subtle">{details}</p>;
  }
  return (
    <pre className="mt-2 max-h-28 max-w-full overflow-auto rounded-xl border border-surface-600 bg-surface-950 p-3 text-xs leading-5 text-ink-subtle">
      <code>{formatJson(details)}</code>
    </pre>
  );
}

function AgentTracePanel({ traceSteps }: { traceSteps?: AgentTraceStep[] }) {
  if (!traceSteps || traceSteps.length === 0) return null;

  return (
    <div className="rounded-2xl border border-surface-600 bg-surface-900/70 p-4">
      <p className="text-xs uppercase tracking-[0.16em] text-ink-subtle">
        Agent Trace
      </p>
      <ol className="mt-4 space-y-4">
        {traceSteps.map((step, index) => (
          <li key={`${step.step_number}-${step.actor}`} className="flex gap-3">
            <div className="flex flex-col items-center">
              <div className="flex h-7 w-7 items-center justify-center rounded-full border border-primary-500/30 bg-primary-500/10 text-xs font-semibold text-primary-700 dark:text-primary-200">
                {step.step_number || index + 1}
              </div>
              {index < traceSteps.length - 1 && (
                <div className="mt-2 h-full min-h-8 w-px bg-surface-600" />
              )}
            </div>
            <div className="min-w-0 flex-1 pb-1">
              <div className="flex flex-wrap items-center gap-2">
                <Circle
                  size={9}
                  className="fill-primary-500 text-primary-500"
                />
                <p className="text-sm font-semibold text-ink">{step.actor}</p>
                <span className={traceStatusClass(step.status)}>
                  {step.status}
                </span>
              </div>
              <p className="mt-1 text-sm text-ink-muted">{step.action}</p>
              <TraceDetails details={step.details} />
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

export default function MultiAgentPage() {
  const [message, setMessage] = useState("show running containers");
  const [contextText, setContextText] = useState(demoContexts.containers);
  const [result, setResult] = useState<AgentOrchestrationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const parsedContextPreview = useMemo(() => {
    try {
      return JSON.parse(contextText || "{}") as Record<string, unknown>;
    } catch {
      return null;
    }
  }, [contextText]);

  const runAgent = async () => {
    const trimmedMessage = message.trim();
    if (!trimmedMessage || loading) return;

    let context: Record<string, unknown>;
    try {
      context = JSON.parse(contextText || "{}") as Record<string, unknown>;
    } catch {
      setError("Context must be valid JSON.");
      return;
    }

    setLoading(true);
    setError("");
    try {
      const response = await agentService.orchestrate(trimmedMessage, context);
      setResult(response);
    } catch (err) {
      setResult(null);
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const applyDemo = (demo: (typeof quickDemos)[number]) => {
    setMessage(demo.message);
    setContextText(demo.context);
    setError("");
  };

  return (
    <div className="flex h-full flex-col bg-surface-900">
      <div className="workspace-page-header shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-primary-500/30 bg-primary-500/10">
            <Network
              size={19}
              className="text-primary-600 dark:text-primary-300"
            />
          </div>
          <div>
            <h1 className="text-base font-semibold text-ink">
              Multi-Agent Orchestration
            </h1>
            <p className="text-xs text-ink-subtle">
              Route one user request through the orchestration agent and
              specialized agents
            </p>
          </div>
        </div>
      </div>

      <div className="workspace-page-body min-h-0 flex-1 overflow-y-auto py-5">
        <div className="mx-auto max-w-6xl space-y-5">
          <section className="card overflow-hidden">
            <div className="border-b border-surface-600 px-5 py-4">
              <div className="flex items-center gap-2">
                <Route
                  size={18}
                  className="text-primary-600 dark:text-primary-300"
                />
                <h2 className="text-sm font-semibold text-ink">
                  Run Agent Flow
                </h2>
              </div>
            </div>

            <div className="space-y-5 p-4 sm:p-5">
              <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
                <div>
                  <label
                    htmlFor="agent-command"
                    className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-subtle"
                  >
                    User Command
                  </label>
                  <textarea
                    id="agent-command"
                    value={message}
                    onChange={(event) => setMessage(event.target.value)}
                    className="input-field mt-3 min-h-36 resize-y p-3 text-sm leading-6"
                    placeholder="show running containers"
                  />
                </div>

                <div>
                  <label
                    htmlFor="agent-context"
                    className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-subtle"
                  >
                    Optional JSON Context
                  </label>
                  <textarea
                    id="agent-context"
                    value={contextText}
                    onChange={(event) => setContextText(event.target.value)}
                    className="input-field mt-3 min-h-36 resize-y p-3 font-mono text-xs leading-5"
                    placeholder='{"repo_full_name":"owner/repo"}'
                  />
                </div>
              </div>

              <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
                <button
                  type="button"
                  onClick={runAgent}
                  disabled={!message.trim() || loading}
                  className="btn-primary w-full sm:w-auto"
                >
                  {loading ? (
                    <Loader2 size={15} className="animate-spin" />
                  ) : (
                    <Play size={15} />
                  )}
                  Run Agent
                </button>
                <span
                  className={
                    parsedContextPreview ? "badge-success" : "badge-error"
                  }
                >
                  <Braces size={12} className="mr-1 inline" />
                  {parsedContextPreview ? "Valid JSON" : "Invalid JSON"}
                </span>
                {error && (
                  <div className="w-full">
                    <div className="inline-flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-200">
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
              </div>
            </div>
          </section>

          <section className="card p-5">
            <div className="mb-4 flex items-center gap-2">
              <Sparkles
                size={18}
                className="text-blue-600 dark:text-blue-300"
              />
              <h2 className="text-sm font-semibold text-ink">
                Quick Demo Buttons
              </h2>
            </div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              {quickDemos.map((demo) => (
                <button
                  key={demo.label}
                  type="button"
                  onClick={() => applyDemo(demo)}
                  className="rounded-2xl border border-surface-600 bg-surface-900/70 p-3 text-left text-sm font-medium text-ink transition hover:border-primary-500/40 hover:bg-primary-500/10 sm:p-4"
                >
                  <Bot
                    size={16}
                    className="mb-3 text-primary-600 dark:text-primary-300"
                  />
                  {demo.label}
                </button>
              ))}
            </div>
          </section>

          {result && <ResultPanel result={result} />}
          {!result && !loading && !error && (
            <section className="card p-8 text-center">
              <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-surface-600 bg-surface-900">
                <Network
                  size={22}
                  className="text-primary-600 dark:text-primary-300"
                />
              </div>
              <p className="font-medium text-ink">Ready to run an agent flow</p>
              <p className="mt-2 text-sm text-ink-subtle">
                Choose a quick demo or enter your own command to see intent,
                selected agent, risk, tool call, and trace steps.
              </p>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
