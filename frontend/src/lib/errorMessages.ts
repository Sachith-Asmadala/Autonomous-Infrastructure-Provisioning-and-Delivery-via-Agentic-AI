/**
 * Friendly error message mapping for common demo failure scenarios
 */

import type { AxiosError } from "axios";

interface ErrorResponse {
  detail?: unknown;
  message?: string;
}

export function getUserFriendlyError(err: unknown): string {
  if (typeof err === "string") return err;
  // Handle network errors (backend not reachable)
  if (err instanceof Error) {
    const message = err.message.toLowerCase();

    // Network connectivity issues
    if (
      message.includes("econnrefused") ||
      message.includes("connection refused")
    ) {
      return "Backend server is not reachable. Please ensure the backend is running on port 8000.";
    }
    if (message.includes("enotfound") || message.includes("getaddrinfo")) {
      return "Cannot reach the backend. Check your connection and backend URL.";
    }
    if (message.includes("timeout")) {
      return "Request timed out. The backend may be slow or unresponsive.";
    }
    if (message.includes("network")) {
      return "Network error. Please check your connection.";
    }
  }

  // Handle Axios/HTTP errors
  const axiosErr = err as AxiosError<ErrorResponse>;
  const status = axiosErr.response?.status;
  const rawDetail = axiosErr.response?.data?.detail;
  const detail = typeof rawDetail === "string" ? rawDetail : undefined;

  if (!status) {
    // No response (network error)
    if (axiosErr.message === "Network Error") {
      return "Backend server is not reachable. Please start the backend with 'make backend'.";
    }
    return "Network error. Please check the backend is running.";
  }

  // Handle status-specific errors
  switch (status) {
    case 400:
      return (
        detail || "Invalid request. Please check your input and try again."
      );

    case 401:
      return "Your session has expired. Please log in again.";

    case 403:
      return "You don't have permission for this action. Contact an admin if needed.";

    case 404:
      return detail || "The requested resource was not found.";

    case 409:
      return detail || "This resource is already in use or has been modified.";

    case 410:
      return "This approval request has expired. Please create a new one.";

    case 422:
      return "Request validation failed. Please check your input.";

    case 429:
      return "Too many requests. Please wait a moment and try again.";

    case 500:
      if (detail?.includes("model") || detail?.includes("Model")) {
        return "The ML model is not available. Please ensure the model file is trained.";
      }
      if (detail?.includes("GitHub")) {
        return "GitHub API error. Check your GitHub token and permissions.";
      }
      if (detail?.includes("docker") || detail?.includes("Docker")) {
        return "Docker daemon is not running. Please start Docker first.";
      }
      if (detail?.includes("GITHUB_TOKEN")) {
        return "GitHub token is not configured. Set GITHUB_TOKEN environment variable or install the GitHub App.";
      }
      if (detail?.includes("webhook")) {
        return "GitHub webhook is not properly configured. Set GITHUB_APP_WEBHOOK_SECRET in the backend.";
      }
      return detail || "Server error. Please check the backend logs.";

    case 503:
      if (detail?.includes("model") || detail?.includes("Model")) {
        return "ML model service is unavailable. Please train the model first.";
      }
      return (
        detail ||
        "A required service is unavailable. Please check the backend logs."
      );

    default:
      return detail || `Error (${status}). Please check the backend logs.`;
  }
}

/**
 * Get helpful debugging hints for common scenarios
 */
export function getDebugHint(err: unknown): string | null {
  const message = getUserFriendlyError(err);

  if (message.includes("not reachable")) {
    return "Run: make backend";
  }
  if (message.includes("model")) {
    return "Run: make train-model";
  }
  if (message.includes("Docker")) {
    return "Start Docker desktop or daemon";
  }
  if (message.includes("GitHub")) {
    return "Check GITHUB_TOKEN or GitHub App installation";
  }
  if (message.includes("expired")) {
    return "Session expired. Log in again.";
  }

  return null;
}

/**
 * Format error for display in UI
 */
export function formatErrorDisplay(
  err: unknown,
  title = "Error",
): { title: string; message: string; hint?: string } {
  const message = getUserFriendlyError(err);
  const hint = getDebugHint(err);

  return {
    title,
    message,
    ...(hint && { hint }),
  };
}
