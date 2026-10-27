import { getDebugHint, getUserFriendlyError } from "@/lib/errorMessages";
import { evaluationService, type EvaluationSummary } from "@/services/api";
import {
  Activity,
  AlertCircle,
  BarChart3,
  CheckSquare,
  ClipboardList,
  Database,
  GitPullRequest,
  Loader2,
  Percent,
  Tags,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useState } from "react";

interface MetricCard {
  label: string;
  value: string;
  icon: typeof Database;
}

const formatNumber = (value: number | null | undefined) =>
  value === null || value === undefined ? "N/A" : value.toLocaleString();

const formatPercent = (value: number | null | undefined) =>
  value === null || value === undefined ? "N/A" : `${(value * 100).toFixed(1)}%`;

function buildCards(summary: EvaluationSummary): MetricCard[] {
  return [
    {
      label: "Dataset Size",
      value: formatNumber(summary.dataset_size),
      icon: Database,
    },
    {
      label: "Failure Classes",
      value: formatNumber(summary.number_of_labels),
      icon: Tags,
    },
    {
      label: "Model Accuracy",
      value: formatPercent(summary.accuracy),
      icon: Percent,
    },
    {
      label: "Macro F1-score",
      value: formatPercent(summary.macro_f1),
      icon: BarChart3,
    },
    {
      label: "Weighted F1-score",
      value: formatPercent(summary.weighted_f1),
      icon: BarChart3,
    },
    {
      label: "Diagnosed Workflow Failures",
      value: formatNumber(summary.total_workflow_failures),
      icon: TriangleAlert,
    },
    {
      label: "Fix PRs Created",
      value: formatNumber(summary.total_fix_prs_created),
      icon: GitPullRequest,
    },
    {
      label: "Audit Logs",
      value: formatNumber(summary.total_audit_logs),
      icon: ClipboardList,
    },
    {
      label: "Approval Requests",
      value: formatNumber(summary.total_approvals),
      icon: CheckSquare,
    },
  ];
}

export default function EvaluationPage() {
  const [summary, setSummary] = useState<EvaluationSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;

    async function loadSummary() {
      setLoading(true);
      setError("");
      try {
        const data = await evaluationService.summary();
        if (mounted) setSummary(data);
      } catch (err: any) {
        if (!mounted) return;
        setSummary(null);
        setError(getUserFriendlyError(err));
      } finally {
        if (mounted) setLoading(false);
      }
    }

    loadSummary();
    return () => {
      mounted = false;
    };
  }, []);

  const cards = summary ? buildCards(summary) : [];

  return (
    <div className="flex h-full flex-col bg-surface-900">
      <div className="workspace-page-header shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-primary-500/30 bg-primary-500/10">
            <Activity
              size={19}
              className="text-primary-600 dark:text-primary-300"
            />
          </div>
          <div>
            <h1 className="text-base font-semibold text-ink">
              Evaluation Dashboard
            </h1>
            <p className="text-xs text-ink-subtle">
              Model metrics and automation evidence for project demo
            </p>
          </div>
        </div>
      </div>

      <div className="workspace-page-body min-h-0 flex-1 overflow-y-auto py-5">
        <div className="mx-auto max-w-6xl">
          {loading ? (
            <div className="flex h-40 items-center justify-center">
              <Loader2
                size={24}
                className="animate-spin text-primary-500 dark:text-primary-300"
              />
            </div>
          ) : error ? (
            <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-red-700 dark:text-red-200">
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
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {cards.map(({ label, value, icon: Icon }) => (
                <div key={label} className="card p-5">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-subtle">
                        {label}
                      </p>
                      <p className="mt-3 text-2xl font-semibold text-ink">
                        {value}
                      </p>
                    </div>
                    <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-surface-600 bg-surface-800 text-primary-600 dark:text-primary-300">
                      <Icon size={18} />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
