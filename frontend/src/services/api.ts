import axios from "axios";
import {
  IS_AUTH_DISABLED,
  IS_DESKTOP_MODE,
  IS_MOBILE_MODE,
} from "@/config/runtime";
import type { RoleProfile, User, UserRole } from "@/types";
import { normalizeRole } from "@/lib/rbac";

export const BACKEND_URL_STORAGE_KEY = "smart_devops_backend_url";

function safeLocalStorageGet(key: string): string {
  try {
    return window.localStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

function safeLocalStorageSet(key: string, value: string): void {
  try {
    if (value) window.localStorage.setItem(key, value);
    else window.localStorage.removeItem(key);
  } catch {
    // Ignore storage failures in restricted webviews.
  }
}

export function normalizeBackendUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

export function getApiBaseUrl(): string {
  const stored = safeLocalStorageGet(BACKEND_URL_STORAGE_KEY);
  const envValue = String(import.meta.env.VITE_API_BASE_URL || "").trim();
  const defaultUrl =
    IS_DESKTOP_MODE || IS_MOBILE_MODE
      ? "http://127.0.0.1:8000"
      : window.location.origin;
  return normalizeBackendUrl(stored || envValue || defaultUrl);
}

export function setStoredBackendUrl(value: string): string {
  const normalized = normalizeBackendUrl(value);
  safeLocalStorageSet(BACKEND_URL_STORAGE_KEY, normalized);
  api.defaults.baseURL = `${getApiBaseUrl()}/api/v1`;
  return normalized;
}

export function clearStoredBackendUrl(): void {
  safeLocalStorageSet(BACKEND_URL_STORAGE_KEY, "");
  api.defaults.baseURL = `${getApiBaseUrl()}/api/v1`;
}

export const API_BASE_URL = getApiBaseUrl();

let inMemoryAccessToken: string | null = null;

function setInMemoryAccessToken(token?: string | null): void {
  inMemoryAccessToken = token || null;
}

export const api = axios.create({
  baseURL: `${getApiBaseUrl()}/api/v1`,
  headers: { "Content-Type": "application/json" },
  withCredentials: true,
});

api.interceptors.request.use((config) => {
  if (inMemoryAccessToken) {
    config.headers.Authorization = `Bearer ${inMemoryAccessToken}`;
  }
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status;
    const url = err.config?.url || "";
    const isAuthProbe =
      url.includes("/auth/me") ||
      url.includes("/auth/login") ||
      url.includes("/auth/logout") ||
      url.includes("/auth/register") ||
      url.includes("/auth/roles");
    if (status === 401 && !IS_AUTH_DISABLED) {
      setInMemoryAccessToken(null);
    }
    if (status === 401 && !isAuthProbe && !IS_AUTH_DISABLED) {
      window.dispatchEvent(new CustomEvent("devops-auth:unauthorized"));
    }
    return Promise.reject(err);
  },
);

export interface LoginResponse {
  access_token?: string;
  refresh_token?: string;
  user?: User;
  user_id?: string;
  username?: string;
  role?: string;
  email?: string;
  id?: string;
  is_active?: boolean;
  created_at?: string;
}

export interface RegisterRequest {
  email: string;
  username: string;
  password: string;
}

export interface AdminCreateUserRequest {
  email: string;
  username: string;
  password: string;
  role: Exclude<UserRole, "admin">;
  is_active?: boolean;
}

export interface UserStatusApproval {
  approval_id: string;
  user: User;
  is_active: boolean;
  status: "approval_required";
}

function normalizeUser(data: LoginResponse | User): User {
  if ("user" in data && data.user)
    return { ...data.user, role: normalizeRole(data.user.role) };
  return {
    id: data.id || ("user_id" in data && data.user_id ? data.user_id : ""),
    email: data.email,
    username: data.username || "",
    role: normalizeRole(data.role),
    is_active: data.is_active,
    created_at: data.created_at,
  };
}

export const authService = {
  login: async (email: string, password: string): Promise<User> => {
    setInMemoryAccessToken(null);
    const res = await api.post<LoginResponse>("/auth/login", {
      email,
      password,
    });
    setInMemoryAccessToken(res.data.access_token);
    return normalizeUser(res.data);
  },
  register: async ({
    email,
    username,
    password,
  }: RegisterRequest): Promise<User> => {
    setInMemoryAccessToken(null);
    const res = await api.post<LoginResponse>("/auth/register", {
      email,
      username,
      password,
    });
    setInMemoryAccessToken(res.data.access_token);
    return normalizeUser(res.data);
  },
  me: async (): Promise<User> => {
    const res = await api.get<User>("/auth/me");
    return normalizeUser(res.data);
  },
  logout: async (): Promise<void> => {
    try {
      await api.post("/auth/logout");
    } finally {
      setInMemoryAccessToken(null);
    }
  },
  roles: async (): Promise<RoleProfile[]> => {
    const res = await api.get<{ roles: RoleProfile[] }>("/auth/roles");
    return res.data.roles;
  },
  listUsers: async (): Promise<User[]> => {
    const res = await api.get<User[]>("/auth/users");
    return res.data.map(normalizeUser);
  },
  createUser: async (payload: AdminCreateUserRequest): Promise<User> => {
    const res = await api.post<User>("/auth/users", payload);
    return normalizeUser(res.data);
  },
  requestUserStatusChange: async (
    userId: string,
    isActive: boolean,
  ): Promise<UserStatusApproval> => {
    const res = await api.post<UserStatusApproval>(
      `/auth/users/${userId}/status-requests`,
      { is_active: isActive },
    );
    return res.data;
  },
};

export interface SystemStatus {
  backend_api: { status: string; message: string };
  desktop_mode: { enabled: boolean; auth_disabled: boolean };
  mobile_supported: boolean;
  docker: { available: boolean; message: string };
  github: { configured: boolean; message: string };
  ml_model: { available: boolean; path: string; message: string };
}

export const healthService = {
  status: async (): Promise<SystemStatus> => {
    const res = await api.get<SystemStatus>("/health/status");
    return res.data;
  },
  testConnection: async (baseUrl: string): Promise<SystemStatus> => {
    const normalized = normalizeBackendUrl(baseUrl);
    const res = await axios.get<SystemStatus>(
      `${normalized}/api/v1/health/status`,
      {
        timeout: 6000,
        withCredentials: true,
      },
    );
    return res.data;
  },
};

export const agentService = {
  chat: async (message: string, sessionId?: string) => {
    const res = await api.post("/agent/chat", {
      message,
      session_id: sessionId,
    });
    return res.data;
  },
  orchestrate: async (
    message: string,
    context: Record<string, unknown> = {},
  ): Promise<AgentOrchestrationResult> => {
    const res = await api.post<AgentOrchestrationResult>("/agent/orchestrate", {
      message,
      context,
    });
    return res.data;
  },
  clearSession: async (sessionId: string) => {
    await api.delete(`/agent/session/${sessionId}`);
  },
};

export interface AgentOrchestrationResult {
  selected_agent: string;
  intent: string;
  risk_level: string;
  success: boolean;
  result: string;
  metadata: Record<string, unknown> & {
    trace_steps?: AgentTraceStep[];
  };
}

export interface AgentTraceStep {
  step_number: number;
  actor: string;
  action: string;
  status: string;
  details?: Record<string, unknown> | string | null;
}

export const approvalService = {
  list: async (scope: "all" | "mine" = "all") => {
    const res = await api.get("/approvals", { params: { scope } });
    return res.data;
  },
  decide: async (approvalId: string, approved: boolean, note?: string) => {
    const res = await api.post(`/approvals/${approvalId}/decide`, {
      approved,
      note,
    });
    return res.data;
  },
};

export const executionService = {
  list: async (
    params: {
      limit?: number;
      tool?: string | null;
      status?: string | null;
      actor?: string | null;
      source?: string | null;
      days?: number;
    } = {},
  ) => {
    const cleaned = Object.fromEntries(
      Object.entries({ limit: 50, ...params }).filter(
        ([, value]) => value !== null && value !== undefined && value !== "",
      ),
    );
    const res = await api.get("/audit", { params: cleaned });
    return res.data;
  },
  get: async (id: string) => {
    const res = await api.get(`/executions/${id}`);
    return res.data;
  },
};

export interface WorkflowFailure {
  id: string;
  repo_full_name: string;
  workflow_run_id: number;
  requested_by?: string | null;
  diagnosis_error?: string | null;
  has_pending_approval?: boolean | null;
  workflow_name: string | null;
  branch: string | null;
  conclusion: string;
  workflow_url: string | null;
  log_excerpt: string | null;
  predicted_label: string | null;
  confidence: number | null;
  suggested_fix: string | null;
  recommendation?: Record<string, unknown> | null;
  fix_pr_url: string | null;
  status: string;
  created_at: string;
  updated_at: string | null;
}

export interface WorkflowFailureFixPRResult {
  workflow_failure_id: string;
  repo_full_name: string;
  status: string;
  approval_id?: string | null;
  branch?: string | null;
  workflow_path?: string | null;
  pull_request_url?: string | null;
  message: string;
  recommendation?: Record<string, unknown> | null;
  approval_details?: Record<string, unknown> | null;
}

export interface WorkflowFailureIntegrationStatus {
  can_download_logs: boolean;
  webhook_configured: boolean;
  default_repository: string | null;
}

export const workflowFailureService = {
  integrationStatus: async (
    signal?: AbortSignal,
  ): Promise<WorkflowFailureIntegrationStatus> => {
    const res = await api.get<WorkflowFailureIntegrationStatus>(
      "/workflow-failures/integration-status",
      { signal },
    );
    return res.data;
  },
  sync: async (
    repoFullName: string,
  ): Promise<{
    failures: WorkflowFailure[];
    imported: number;
    diagnosed: number;
    message: string;
  }> => {
    const res = await api.post("/workflow-failures/sync", {
      repo_full_name: repoFullName,
    });
    return res.data;
  },
  importLogs: async (request: {
    repo_full_name: string;
    workflow_run_id: number;
    log_text: string;
    workflow_name?: string;
    branch?: string;
  }): Promise<WorkflowFailure> => {
    const res = await api.post<WorkflowFailure>(
      "/workflow-failures/import",
      request,
    );
    return res.data;
  },
  list: async (
    limit = 200,
    signal?: AbortSignal,
  ): Promise<WorkflowFailure[]> => {
    const res = await api.get<WorkflowFailure[]>("/workflow-failures", {
      params: { limit },
      signal,
    });
    return res.data;
  },
  get: async (id: string): Promise<WorkflowFailure> => {
    const res = await api.get<WorkflowFailure>(`/workflow-failures/${id}`);
    return res.data;
  },
  createFixPr: async (id: string): Promise<WorkflowFailureFixPRResult> => {
    const res = await api.post<WorkflowFailureFixPRResult>(
      `/workflow-failures/${id}/create-fix-pr`,
    );
    return res.data;
  },
};

export interface FailurePrediction {
  label: string;
  confidence: number | null;
  suggested_fix: string;
  recommendation?: Record<string, unknown>;
}

export interface DetectedStack {
  language: string;
  framework: string;
  package_manager: string;
  has_docker: boolean;
  has_existing_workflows: boolean;
  recommended_workflow: string;
  project_dir: string;
  detected_projects: Array<{
    type: string;
    path: string;
    framework: string;
    package_manager: string;
  }>;
  ci_warnings: Array<{
    severity: string;
    path: string;
    issue: string;
    recommendation: string;
  }>;
}

export interface GeneratedWorkflow {
  stack: DetectedStack;
  path: string;
  workflow_yaml: string;
}

export interface RepositoryScanResult {
  repo_full_name: string;
  files: string[];
  stack: DetectedStack;
  readiness: {
    score: number;
    grade: string;
    summary: string;
    strengths: string[];
    findings: Array<{
      severity: string;
      category: string;
      title: string;
      detail: string;
      recommendation: string;
    }>;
    recommended_next_actions: string[];
  };
}

export interface WorkflowPRResult {
  repo_full_name: string;
  detected_stack?: DetectedStack;
  branch?: string;
  workflow_path?: string;
  pull_request_url?: string;
  status?: "approval_required" | "completed" | "failed" | string;
  approval_required?: boolean;
  approval_id?: string;
  message?: string;
  execution_id?: string;
  execution_status?: string;
  expires_at?: string;
  approval_status?: string;
}

export interface EvaluationSummary {
  dataset_size: number | null;
  number_of_labels: number | null;
  accuracy: number | null;
  macro_f1: number | null;
  weighted_f1: number | null;
  total_workflow_failures: number;
  total_fix_prs_created: number;
  total_audit_logs: number;
  total_approvals: number;
}

export const evaluationService = {
  summary: async (): Promise<EvaluationSummary> => {
    const res = await api.get<EvaluationSummary>("/evaluation/summary");
    return res.data;
  },
};

export const repositoryService = {
  integrationStatus: async (signal?: AbortSignal) => {
    const res = await api.get<{ credentials_configured: boolean }>(
      "/repositories/integration-status",
      { signal },
    );
    return res.data;
  },
  workflowPrStatus: async (
    repoFullName: string,
    overwriteExistingWorkflow = false,
    signal?: AbortSignal,
    approvalId?: string | null,
  ): Promise<WorkflowPRResult | null> => {
    const res = await api.get<WorkflowPRResult | null>(
      "/repositories/workflow-pr-status",
      {
        params: {
          repo_full_name: repoFullName,
          overwrite_existing_workflow: overwriteExistingWorkflow,
          ...(approvalId ? { approval_id: approvalId } : {}),
        },
        signal,
      },
    );
    return res.data;
  },
  scan: async (repoFullName: string): Promise<RepositoryScanResult> => {
    const res = await api.post<RepositoryScanResult>("/repositories/scan", {
      repo_full_name: repoFullName,
    });
    return res.data;
  },
  createWorkflowPr: async (
    repoFullName: string,
    overwriteExistingWorkflow = false,
  ): Promise<WorkflowPRResult> => {
    const res = await api.post<WorkflowPRResult>(
      "/repositories/create-workflow-pr",
      {
        repo_full_name: repoFullName,
        overwrite_existing_workflow: overwriteExistingWorkflow,
      },
    );
    return res.data;
  },
};

export const cicdAssistantService = {
  predictFailure: async (logText: string): Promise<FailurePrediction> => {
    const res = await api.post<FailurePrediction>("/model/predict-failure", {
      log_text: logText,
    });
    return res.data;
  },
  generateWorkflow: async (files: string[]): Promise<GeneratedWorkflow> => {
    const res = await api.post<GeneratedWorkflow>("/cicd/generate-workflow", {
      files,
    });
    return res.data;
  },
};
