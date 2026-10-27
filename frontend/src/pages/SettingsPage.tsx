import {
  clearStoredBackendUrl,
  getApiBaseUrl,
  healthService,
  setStoredBackendUrl,
  type SystemStatus,
} from "@/services/api";
import {
  IS_AUTH_DISABLED,
  IS_DESKTOP_MODE,
  IS_MOBILE_MODE,
} from "@/config/runtime";
import { getDebugHint, getUserFriendlyError } from "@/lib/errorMessages";
import {
  AlertCircle,
  CheckCircle2,
  Globe2,
  KeyRound,
  Loader2,
  Monitor,
  Server,
  Settings,
  Wifi,
} from "lucide-react";
import { useEffect, useState } from "react";

function SettingRow({
  icon: Icon,
  label,
  value,
  ok,
  note,
}: {
  icon: typeof Settings;
  label: string;
  value: string;
  ok?: boolean;
  note: string;
}) {
  return (
    <div className="rounded-2xl border border-surface-600 bg-surface-900/70 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-surface-600 bg-surface-800">
            <Icon size={17} className="text-primary-600 dark:text-primary-300" />
          </div>
          <div>
            <p className="text-sm font-semibold text-ink">{label}</p>
            <p className="mt-1 break-words font-mono text-xs text-ink-subtle">
              {value}
            </p>
          </div>
        </div>
        {typeof ok === "boolean" && (
          <span className={ok ? "badge-success" : "badge-warning"}>
            {ok ? "Configured" : "Not configured"}
          </span>
        )}
      </div>
      <p className="mt-3 text-sm leading-6 text-ink-subtle">{note}</p>
    </div>
  );
}

export default function SettingsPage() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [backendUrl, setBackendUrl] = useState(getApiBaseUrl());
  const [connectionStatus, setConnectionStatus] = useState("");
  const [testingConnection, setTestingConnection] = useState(false);

  const refreshStatus = () => {
    let mounted = true;
    setLoading(true);
    setError("");
    healthService
      .status()
      .then((data) => {
        if (mounted) setStatus(data);
      })
      .catch((err) => {
        if (mounted) setError(getUserFriendlyError(err));
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  };

  useEffect(() => {
    return refreshStatus();
  }, []);

  const saveBackendUrl = () => {
    try {
      const parsed = new URL(backendUrl);
      if (!["http:", "https:"].includes(parsed.protocol)) {
        setConnectionStatus("Invalid URL. Use http:// or https://.");
        return;
      }
      const saved = setStoredBackendUrl(backendUrl);
      setBackendUrl(saved);
      setConnectionStatus("Backend API URL saved.");
      refreshStatus();
    } catch {
      setConnectionStatus("Invalid URL. Example: http://192.168.1.10:8000");
    }
  };

  const clearBackendUrl = () => {
    clearStoredBackendUrl();
    const fallback = getApiBaseUrl();
    setBackendUrl(fallback);
    setConnectionStatus("Backend API URL reset to the build default.");
    refreshStatus();
  };

  const testConnection = async () => {
    setTestingConnection(true);
    setConnectionStatus("");
    try {
      const parsed = new URL(backendUrl);
      if (!["http:", "https:"].includes(parsed.protocol)) {
        setConnectionStatus("Invalid URL. Use http:// or https://.");
        return;
      }
      const result = await healthService.testConnection(backendUrl);
      setStatus(result);
      if (result.desktop_mode?.auth_disabled) {
        setConnectionStatus("Connected. Backend is running with auth disabled.");
      } else if (result.desktop_mode?.enabled) {
        setConnectionStatus("Connected. Backend is running in desktop mode.");
      } else {
        setConnectionStatus("Connected. Backend is reachable; login/RBAC may be required.");
      }
    } catch (err) {
      const message = getUserFriendlyError(err);
      if (message.toLowerCase().includes("unauthorized")) {
        setConnectionStatus("Backend is running but auth is required.");
      } else {
        setConnectionStatus("Cannot reach backend. Check URL, Wi-Fi, CORS, and backend server.");
      }
    } finally {
      setTestingConnection(false);
    }
  };

  return (
    <div className="flex h-full flex-col bg-surface-900">
      <div className="workspace-page-header shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-primary-500/30 bg-primary-500/10">
            <Monitor
              size={19}
              className="text-primary-600 dark:text-primary-300"
            />
          </div>
          <div>
            <h1 className="text-base font-semibold text-ink">Settings</h1>
            <p className="text-xs text-ink-subtle">
              Backend connection and integration readiness
            </p>
          </div>
        </div>
      </div>

      <div className="workspace-page-body min-h-0 flex-1 overflow-y-auto py-5">
        <div className="mx-auto max-w-5xl space-y-5">
          {loading ? (
            <div className="flex h-28 items-center justify-center">
              <Loader2 size={24} className="animate-spin text-primary-500" />
            </div>
          ) : error ? (
            <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-red-700 dark:text-red-200">
              <div className="flex items-start gap-3">
                <AlertCircle size={18} className="mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-semibold">{error}</p>
                  {getDebugHint(error) && (
                    <p className="mt-1 text-xs opacity-80">
                      Tip: {getDebugHint(error)}
                    </p>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="grid gap-4">
              <div className="rounded-2xl border border-surface-600 bg-surface-900/70 p-4">
                <div className="flex items-start gap-3">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-surface-600 bg-surface-800">
                    <Wifi
                      size={17}
                      className="text-primary-600 dark:text-primary-300"
                    />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-ink">
                      Backend API URL
                    </p>
                    <p className="mt-1 text-sm leading-6 text-ink-subtle">
                      Use your PC LAN IP, hosted backend, or ngrok URL. On a
                      phone, 127.0.0.1 means the phone itself.
                    </p>
                    <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:flex xl:flex-wrap">
                      <input
                        value={backendUrl}
                        onChange={(event) => setBackendUrl(event.target.value)}
                        className="input-field min-h-11 px-3 xl:min-w-80 xl:flex-1"
                        placeholder="http://192.168.1.10:8000"
                      />
                      <button
                        type="button"
                        onClick={saveBackendUrl}
                        className="btn-primary min-h-11"
                      >
                        Save
                      </button>
                      <button
                        type="button"
                        onClick={testConnection}
                        disabled={testingConnection}
                        className="btn-ghost min-h-11 border border-surface-600"
                      >
                        {testingConnection ? "Testing..." : "Test Connection"}
                      </button>
                      <button
                        type="button"
                        onClick={clearBackendUrl}
                        className="btn-ghost min-h-11 border border-surface-600"
                      >
                        Reset
                      </button>
                    </div>
                    {connectionStatus && (
                      <p className="mt-3 text-sm font-medium text-ink">
                        {connectionStatus}
                      </p>
                    )}
                  </div>
                </div>
              </div>
              <SettingRow
                icon={CheckCircle2}
                label="App Mode"
                value={
                  IS_MOBILE_MODE
                    ? "Mobile"
                    : IS_DESKTOP_MODE
                      ? "Desktop"
                      : "Web"
                }
                ok={IS_MOBILE_MODE || IS_DESKTOP_MODE}
                note={
                  IS_AUTH_DISABLED
                    ? "Local auth is disabled in this build, so the app opens without login."
                    : "Login/RBAC remains enabled unless the backend and frontend are configured for local auth bypass."
                }
              />
              <SettingRow
                icon={Server}
                label="Active Backend"
                value={getApiBaseUrl()}
                ok={Boolean(status?.backend_api.status === "ok")}
                note="The API client uses the saved URL first, then VITE_API_BASE_URL. Web mode defaults to this site's origin; desktop and mobile default to http://127.0.0.1:8000."
              />
              <SettingRow
                icon={KeyRound}
                label="GitHub Token Status"
                value={status?.github.configured ? "Configured" : "Not configured"}
                ok={Boolean(status?.github.configured)}
                note="Set GITHUB_TOKEN or GitHub App credentials through backend environment variables. Token values are never shown in the UI."
              />
              <SettingRow
                icon={Globe2}
                label="Webhook / ngrok"
                value="Public tunnel required for local webhook testing"
                note="GitHub cannot deliver webhooks to a private desktop address without ngrok or another public tunnel."
              />
              <SettingRow
                icon={Monitor}
                label={IS_MOBILE_MODE ? "Docker Backend Note" : "Docker Desktop"}
                value={status?.docker.available ? "Running" : "Not reachable"}
                ok={Boolean(status?.docker.available)}
                note={
                  IS_MOBILE_MODE
                    ? "Docker operations run on the backend machine, not on the phone."
                    : "Docker actions require Docker Desktop running on this machine."
                }
              />
              {IS_MOBILE_MODE && (
                <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm leading-6 text-amber-800 dark:text-amber-100">
                  Mobile limitations: the backend must be reachable, GitHub
                  webhooks require a hosted backend or ngrok, GitHub tokens stay
                  in backend environment variables, and offline GitHub/ML
                  operations are not supported.
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
