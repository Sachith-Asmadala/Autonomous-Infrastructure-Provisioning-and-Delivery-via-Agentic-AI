import type { UserRole } from "@/types";

export interface RoleDefinition {
  role: UserRole;
  label: string;
  description: string;
  headline: string;
  permissions: readonly string[];
  badgeClass: string;
  accentClass: string;
}

export const ROLE_ORDER: UserRole[] = ["admin", "developer"];

export const ROLE_DEFINITIONS: Record<UserRole, RoleDefinition> = {
  admin: {
    role: "admin",
    label: "Admin",
    description:
      "Full platform owner with user management, audit, approval, and infrastructure permissions.",
    headline: "Full control plane access",
    permissions: ["*"],
    badgeClass:
      "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-200",
    accentClass: "text-rose-600 dark:text-rose-300",
  },
  developer: {
    role: "developer",
    label: "Developer",
    description:
      "Build CI/CD workflows, propose workflow pull requests, review your own approvals, and use development/staging tools.",
    headline: "CI/CD and personal approvals",
    permissions: [
      "agent:chat",
      "approvals:read",
      "approvals:decide:own",
      "agents:orchestrate",
      "cicd:read",
      "cicd:generate",
      "failures:predict",
      "repositories:read",
      "repositories:write",
      "workflow_failures:read",
      "executions:read",
      "logs:read",
      "deployments:staging",
    ],
    badgeClass:
      "border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-200",
    accentClass: "text-sky-600 dark:text-sky-300",
  },
};

export const CHAT_SUGGESTIONS: Record<UserRole, string[]> = {
  admin: [
    "Show pending approvals and recent failed executions.",
    "Summarize infrastructure risks from the latest activity.",
    "Create a delivery checklist for today.",
  ],
  developer: [
    "Diagnose the latest CI failure logs.",
    "Suggest a staging deployment plan.",
    "Explain recent execution failures.",
  ],
};

export function normalizeRole(role?: string | null): UserRole {
  const value = String(role || "").toLowerCase();
  if (value === "admin" || value === "developer") return value;
  throw new Error("Unsupported account role. Please sign in again.");
}

export function getRoleDefinition(role?: string | null): RoleDefinition {
  if (role === "admin" || role === "developer") return ROLE_DEFINITIONS[role];
  return {
    ...ROLE_DEFINITIONS.developer,
    label: "Account unavailable",
    description: "Sign in with an active workspace account.",
    permissions: [],
  };
}

export function hasPermission(
  role: string | null | undefined,
  permission: string,
): boolean {
  const permissions = getRoleDefinition(role).permissions;
  return permissions.includes("*") || permissions.includes(permission);
}

export function defaultPathForRole(role?: string | null): string {
  return role ? "/dashboard" : "/chat";
}

export function canAccessPath(
  role: string | null | undefined,
  path: string,
): boolean {
  if (path.startsWith("/dashboard") || path.startsWith("/settings")) {
    return role === "admin" || role === "developer";
  }
  if (path.startsWith("/users")) return hasPermission(role, "users:manage");
  if (path.startsWith("/diagnosis"))
    return (
      hasPermission(role, "failures:predict") ||
      hasPermission(role, "cicd:generate")
    );
  if (path.startsWith("/repository-setup"))
    return hasPermission(role, "repositories:write");
  if (path.startsWith("/workflow-failures"))
    return hasPermission(role, "workflow_failures:read");
  if (path.startsWith("/approvals"))
    return hasPermission(role, "approvals:read");
  if (path.startsWith("/executions"))
    return hasPermission(role, "executions:read");
  if (path.startsWith("/evaluation"))
    return hasPermission(role, "metrics:read");
  if (path.startsWith("/multi-agent"))
    return hasPermission(role, "agents:orchestrate");
  if (path.startsWith("/chat") || path === "/")
    return hasPermission(role, "agent:chat");
  return false;
}
