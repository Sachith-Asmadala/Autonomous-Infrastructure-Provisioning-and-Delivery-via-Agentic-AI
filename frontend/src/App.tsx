import { useEffect, type ReactNode } from "react";
import {
  BrowserRouter,
  HashRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { ShieldAlert } from "lucide-react";
import Layout from "@/components/layout/Layout";
import ChatPage from "@/pages/ChatPage";
import ApprovalsPage from "@/pages/ApprovalsPage";
import DashboardPage from "@/pages/DashboardPage";
import DiagnosisPage from "@/pages/DiagnosisPage";
import EvaluationPage from "@/pages/EvaluationPage";
import ExecutionsPage from "@/pages/ExecutionsPage";
import LandingPage from "@/pages/LandingPage";
import LoginPage from "@/pages/LoginPage";
import MultiAgentPage from "@/pages/MultiAgentPage";
import RepositorySetupPage from "@/pages/RepositorySetupPage";
import SettingsPage from "@/pages/SettingsPage";
import UsersPage from "@/pages/UsersPage";
import WorkflowFailuresPage from "@/pages/WorkflowFailuresPage";
import {
  DESKTOP_HOME_PATH,
  IS_AUTH_DISABLED,
  IS_DESKTOP_MODE,
  IS_MOBILE_MODE,
} from "@/config/runtime";
import { useAuthStore } from "@/store/authStore";
import { useThemeStore } from "@/store/themeStore";
import {
  canAccessPath,
  defaultPathForRole,
  getRoleDefinition,
} from "@/lib/rbac";

function AppLoader() {
  return (
    <div className="flex min-h-screen items-center justify-center app-bg">
      <div className="flex items-center gap-3 rounded-2xl border border-surface-600 bg-surface-800 px-5 py-4 shadow-panel">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary-400/30 border-t-primary-500" />
        <span className="text-sm text-ink-muted">Checking secure session…</span>
      </div>
    </div>
  );
}

function AccessDenied() {
  const { user } = useAuthStore();
  const role = getRoleDefinition(user?.role);
  return (
    <div className="flex h-full items-center justify-center bg-surface-900 px-4">
      <div className="glass-panel max-w-lg p-8 text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-3xl border border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-300">
          <ShieldAlert size={28} />
        </div>
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-600 dark:text-amber-300">
          Access restricted
        </p>
        <h1 className="mt-3 text-2xl font-semibold text-ink">
          This option is not enabled for {role.label} accounts.
        </h1>
        <p className="mt-3 text-sm leading-6 text-ink-muted">
          {role.description}
        </p>
        <a
          href={defaultPathForRole(user?.role)}
          className="mt-6 inline-flex rounded-2xl bg-primary-600 px-4 py-2.5 text-sm font-semibold text-white shadow-glow transition hover:bg-primary-500"
        >
          Go to your workspace
        </a>
      </div>
    </div>
  );
}

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuthStore();
  const location = useLocation();

  if (IS_AUTH_DISABLED) return <>{children}</>;
  if (isLoading) return <AppLoader />;
  return isAuthenticated ? (
    <>{children}</>
  ) : (
    <Navigate to="/login" state={{ from: location }} replace />
  );
}

function RoleProtectedRoute({ children }: { children: ReactNode }) {
  const { user } = useAuthStore();
  const location = useLocation();
  if (
    (IS_AUTH_DISABLED || IS_MOBILE_MODE) &&
    location.pathname.startsWith("/users")
  ) {
    return <Navigate to={DESKTOP_HOME_PATH} replace />;
  }
  if (IS_AUTH_DISABLED) return <>{children}</>;
  return canAccessPath(user?.role, location.pathname) ? (
    <>{children}</>
  ) : (
    <AccessDenied />
  );
}

function AppRoutes() {
  const { checkAuth, markUnauthenticated } = useAuthStore();

  useEffect(() => {
    if (IS_AUTH_DISABLED) return;
    const handleUnauthorized = () => markUnauthenticated();
    window.addEventListener("devops-auth:unauthorized", handleUnauthorized);
    return () =>
      window.removeEventListener(
        "devops-auth:unauthorized",
        handleUnauthorized,
      );
  }, [markUnauthenticated]);

  useEffect(() => {
    void checkAuth();
  }, [checkAuth]);

  return (
    <Routes>
      <Route
        path="/"
        element={
          IS_AUTH_DISABLED ? (
            <Navigate to={DESKTOP_HOME_PATH} replace />
          ) : (
            <LandingPage />
          )
        }
      />
      <Route
        path="/signup"
        element={
          IS_AUTH_DISABLED ? (
            <Navigate to={DESKTOP_HOME_PATH} replace />
          ) : (
            <LoginPage key="signup" mode="signup" />
          )
        }
      />
      <Route
        path="/login"
        element={
          IS_AUTH_DISABLED ? (
            <Navigate to={DESKTOP_HOME_PATH} replace />
          ) : (
            <LoginPage key="login" />
          )
        }
      />
      <Route
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route
          path="dashboard"
          element={
            <RoleProtectedRoute>
              <DashboardPage />
            </RoleProtectedRoute>
          }
        />
        <Route
          path="chat"
          element={
            <RoleProtectedRoute>
              <ChatPage />
            </RoleProtectedRoute>
          }
        />
        <Route
          path="multi-agent"
          element={
            <RoleProtectedRoute>
              <MultiAgentPage />
            </RoleProtectedRoute>
          }
        />
        <Route
          path="diagnosis"
          element={
            <RoleProtectedRoute>
              <DiagnosisPage />
            </RoleProtectedRoute>
          }
        />
        <Route
          path="repository-setup"
          element={
            <RoleProtectedRoute>
              <RepositorySetupPage />
            </RoleProtectedRoute>
          }
        />
        <Route
          path="workflow-failures"
          element={
            <RoleProtectedRoute>
              <WorkflowFailuresPage />
            </RoleProtectedRoute>
          }
        />
        <Route
          path="approvals"
          element={
            <RoleProtectedRoute>
              <ApprovalsPage />
            </RoleProtectedRoute>
          }
        />
        <Route
          path="executions"
          element={
            <RoleProtectedRoute>
              <ExecutionsPage />
            </RoleProtectedRoute>
          }
        />
        <Route
          path="evaluation"
          element={
            <RoleProtectedRoute>
              <EvaluationPage />
            </RoleProtectedRoute>
          }
        />
        <Route
          path="settings"
          element={
            <RoleProtectedRoute>
              <SettingsPage />
            </RoleProtectedRoute>
          }
        />
        <Route
          path="users"
          element={
            <RoleProtectedRoute>
              <UsersPage />
            </RoleProtectedRoute>
          }
        />
      </Route>
    </Routes>
  );
}

export default function App() {
  const { syncSystemTheme } = useThemeStore();
  const Router =
    IS_DESKTOP_MODE || window.location.protocol === "file:"
      ? HashRouter
      : BrowserRouter;

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const sync = () => syncSystemTheme();
    sync();
    media.addEventListener?.("change", sync);
    return () => media.removeEventListener?.("change", sync);
  }, [syncSystemTheme]);

  return (
    <Router future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
      <AppRoutes />
    </Router>
  );
}
