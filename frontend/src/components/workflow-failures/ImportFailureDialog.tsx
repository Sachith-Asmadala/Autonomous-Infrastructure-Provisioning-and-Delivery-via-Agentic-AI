import { useState, type FormEvent } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { AlertCircle, Download, FileText, Loader2, X } from "lucide-react";
import { workflowFailureService, type WorkflowFailure } from "@/services/api";
import { getUserFriendlyError } from "@/lib/errorMessages";

export function ImportFailureDialog({
  defaultRepository,
  failure,
  onClose,
  onImported,
}: {
  defaultRepository?: string | null;
  failure?: WorkflowFailure | null;
  onClose: () => void;
  onImported: (message: string) => void;
}) {
  const [mode, setMode] = useState<"github" | "logs">(
    failure ? "logs" : "github",
  );
  const [repository, setRepository] = useState(
    failure?.repo_full_name || defaultRepository || "",
  );
  const [runUrl, setRunUrl] = useState(failure?.workflow_url || "");
  const [logText, setLogText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setError("");
    if (mode === "logs" && !logText.trim()) {
      setError("Paste the failed run’s logs before diagnosing.");
      return;
    }
    const match = runUrl
      .trim()
      .match(
        /^https:\/\/github\.com\/([\w.-]+\/[\w.-]+)\/actions\/runs\/([1-9]\d*)(?:[/?#].*)?$/,
      );
    if (mode === "logs" && !match) {
      setError(
        "Enter a GitHub Actions run URL, such as https://github.com/owner/repo/actions/runs/12345.",
      );
      return;
    }
    setBusy(true);
    try {
      if (mode === "github") {
        const result = await workflowFailureService.sync(repository.trim());
        onImported(result.message);
      } else if (match) {
        await workflowFailureService.importLogs({
          repo_full_name: match[1],
          workflow_run_id: Number(match[2]),
          log_text: logText.trim(),
          workflow_name: failure?.workflow_name || undefined,
          branch: failure?.branch || undefined,
        });
        onImported("Diagnosis saved. The failed run is now in your workspace.");
      }
      onClose();
    } catch (err: unknown) {
      setError(getUserFriendlyError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/50 backdrop-blur-sm" />
        <Dialog.Content
          onEscapeKeyDown={(event) => {
            if (busy) event.preventDefault();
          }}
          onInteractOutside={(event) => {
            if (busy) event.preventDefault();
          }}
          className="fixed left-1/2 top-1/2 z-50 max-h-[90dvh] w-[calc(100%-2rem)] max-w-2xl -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl border border-surface-600 bg-surface-800 p-6 shadow-xl"
        >
          <div className="flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="text-xl font-semibold text-ink">
                Import workflow failures
              </Dialog.Title>
              <Dialog.Description className="mt-2 text-sm leading-6 text-ink-subtle">
                Load existing failed runs from GitHub, or diagnose a run using
                its build logs.
              </Dialog.Description>
            </div>
            <Dialog.Close
              disabled={busy}
              aria-label="Close failure import"
              className="btn-ghost p-2"
            >
              <X size={18} />
            </Dialog.Close>
          </div>
          <div
            className="my-5 flex gap-2"
            role="group"
            aria-label="Import method"
          >
            {(["github", "logs"] as const).map((value) => (
              <button
                key={value}
                type="button"
                disabled={busy}
                aria-pressed={mode === value}
                onClick={() => {
                  setMode(value);
                  setError("");
                }}
                className={mode === value ? "btn-primary" : "btn-secondary"}
              >
                {value === "github" ? (
                  <Download size={15} />
                ) : (
                  <FileText size={15} />
                )}
                {value === "github" ? "Load from GitHub" : "Paste run logs"}
              </button>
            ))}
          </div>
          {error && (
            <div
              role="alert"
              className="mb-4 flex items-start gap-2 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-700 dark:text-red-200"
            >
              <AlertCircle size={17} className="mt-0.5 shrink-0" />
              {error}
            </div>
          )}
          <form onSubmit={submit} aria-busy={busy}>
            <fieldset disabled={busy} className="space-y-4">
              {mode === "github" ? (
                <div>
                  <label
                    htmlFor="failure-repository"
                    className="mb-2 block text-xs font-medium text-ink-muted"
                  >
                    Repository
                  </label>
                  <input
                    id="failure-repository"
                    value={repository}
                    onChange={(event) => setRepository(event.target.value)}
                    placeholder="owner/repository"
                    className="input-field px-3 py-2.5"
                    required
                    pattern="[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
                    maxLength={255}
                  />
                  <p className="mt-2 text-xs leading-5 text-ink-subtle">
                    Loads the 10 most recent failed or timed-out runs. Public
                    run details are available without a token; automatic log
                    download needs GitHub access.
                  </p>
                </div>
              ) : (
                <>
                  <div>
                    <label
                      htmlFor="failure-run-url"
                      className="mb-2 block text-xs font-medium text-ink-muted"
                    >
                      Workflow run URL
                    </label>
                    <input
                      id="failure-run-url"
                      type="url"
                      value={runUrl}
                      onChange={(event) => setRunUrl(event.target.value)}
                      placeholder="https://github.com/owner/repo/actions/runs/12345"
                      className="input-field px-3 py-2.5"
                      required
                    />
                  </div>
                  <div>
                    <label
                      htmlFor="failure-run-logs"
                      className="mb-2 block text-xs font-medium text-ink-muted"
                    >
                      Failed run logs
                    </label>
                    <textarea
                      id="failure-run-logs"
                      value={logText}
                      onChange={(event) => setLogText(event.target.value)}
                      placeholder="Paste the failed job’s logs from GitHub Actions…"
                      className="input-field min-h-[200px] resize-y px-3 py-2.5 font-mono text-xs"
                      maxLength={200000}
                      required
                    />
                    <p className="mt-2 text-xs leading-5 text-ink-subtle">
                      The trained model diagnoses these logs and saves a
                      recommendation with this run.
                    </p>
                  </div>
                </>
              )}
              <div className="flex justify-end gap-2 border-t border-surface-600 pt-4">
                <button
                  type="button"
                  onClick={onClose}
                  className="btn-secondary"
                >
                  Cancel
                </button>
                <button type="submit" className="btn-primary">
                  {busy ? (
                    <Loader2 size={15} className="animate-spin" />
                  ) : (
                    <Download size={15} />
                  )}
                  {busy
                    ? "Importing…"
                    : mode === "github"
                      ? "Load failed runs"
                      : "Diagnose and save"}
                </button>
              </div>
            </fieldset>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
