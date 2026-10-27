import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  Eye,
  EyeOff,
  GitBranch,
  GitPullRequest,
  Loader2,
  ShieldCheck,
} from "lucide-react";
import { isAxiosError } from "axios";
import Brand from "@/components/public/Brand";
import { useAuthStore } from "@/store/authStore";
import { canAccessPath, defaultPathForRole } from "@/lib/rbac";
import { getUserFriendlyError } from "@/lib/errorMessages";
import "@/styles/public.css";

export default function LoginPage({
  mode = "login",
}: {
  mode?: "login" | "signup";
}) {
  const isSignup = mode === "signup";
  const { login, signup, user, isAuthenticated, isLoading } = useAuthStore();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const from = (
    location.state as { from?: { pathname?: string; search?: string } } | null
  )?.from;
  const requestedPath = from?.pathname;
  const destination =
    requestedPath?.startsWith("/") &&
    !requestedPath.startsWith("//") &&
    canAccessPath(user?.role, requestedPath)
      ? requestedPath + (from?.search || "")
      : defaultPathForRole(user?.role);

  if (isAuthenticated) return <Navigate to={destination} replace />;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    if (isSignup && password !== confirmation) {
      setError("Passwords do not match.");
      return;
    }
    setError("");
    setSubmitting(true);
    try {
      if (isSignup) await signup(email.trim(), username.trim(), password);
      else await login(email.trim(), password);
    } catch (err: unknown) {
      const detail: unknown = isAxiosError(err)
        ? err.response?.data?.detail
        : undefined;
      setError(typeof detail === "string" ? detail : getUserFriendlyError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="public-page auth-page screen-scroll">
      <header className="public-nav public-container">
        <Brand />
        <Link to="/" className="public-text-link">
          <ArrowLeft size={15} /> Back to home
        </Link>
      </header>
      <main className="auth-layout public-container">
        <section className="auth-story" aria-labelledby="auth-story-title">
          <p className="public-eyebrow">YOUR NEXT CHAPTER IN DELIVERY</p>
          <h2 id="auth-story-title">
            Good work.
            <br />
            Clear direction.
            <br />
            <span className="public-serif">Your workspace.</span>
          </h2>
          <p>
            A quieter place to understand failures, shape workflows, and keep
            delivery moving.
          </p>
          <div className="auth-flow" aria-hidden="true">
            <span>
              <GitBranch size={22} />
            </span>
            <i />
            <span>
              <GitPullRequest size={22} />
            </span>
            <i />
            <span className="auth-flow-end">
              <ShieldCheck size={22} />
            </span>
          </div>
          <div className="auth-story-foot">
            <span className="public-status-dot" /> INTELLIGENCE, WITH YOU IN
            CONTROL.
          </div>
        </section>
        <section className="auth-form-panel" aria-labelledby="auth-title">
          <p className="public-eyebrow">
            {isSignup
              ? "LET’S BUILD SOMETHING BETTER"
              : "PICK UP WHERE YOU LEFT OFF"}
          </p>
          <h1 id="auth-title">
            {isSignup ? "Make room for better work." : "Welcome back."}
          </h1>
          <p className="auth-description">
            {isSignup
              ? "Create an account and bring your delivery workflow into focus."
              : "Sign in to your personal delivery workspace."}
          </p>
          <form onSubmit={submit} className="auth-form" aria-busy={submitting}>
            {error && (
              <div role="alert" className="auth-error">
                {error}
              </div>
            )}
            <fieldset disabled={submitting || isLoading}>
              {isSignup && (
                <div className="auth-field">
                  <label htmlFor="username">Username</label>
                  <input
                    id="username"
                    name="username"
                    autoComplete="username"
                    placeholder="e.g. alex.morgan"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    minLength={3}
                    maxLength={50}
                    pattern=".*\S.*"
                    required
                  />
                </div>
              )}
              <div className="auth-field">
                <label htmlFor="email">Email address</label>
                <input
                  id="email"
                  name="email"
                  type="email"
                  autoComplete={isSignup ? "email" : "username"}
                  placeholder="you@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
              <div className="auth-field">
                <label htmlFor="password">Password</label>
                <div className="auth-password">
                  <input
                    id="password"
                    name="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete={
                      isSignup ? "new-password" : "current-password"
                    }
                    placeholder={
                      isSignup ? "At least 8 characters" : "Enter your password"
                    }
                    minLength={isSignup ? 8 : undefined}
                    maxLength={isSignup ? 72 : undefined}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    aria-describedby={isSignup ? "password-hint" : undefined}
                    required
                  />
                  <button
                    type="button"
                    aria-label={
                      showPassword ? "Hide password" : "Show password"
                    }
                    aria-pressed={showPassword}
                    onClick={() => setShowPassword(!showPassword)}
                  >
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
                {isSignup && (
                  <p id="password-hint">Use at least 8 characters.</p>
                )}
              </div>
              {isSignup && (
                <div className="auth-field">
                  <label htmlFor="confirmation">Confirm password</label>
                  <input
                    id="confirmation"
                    name="confirmation"
                    type={showPassword ? "text" : "password"}
                    autoComplete="new-password"
                    placeholder="Enter your password again"
                    value={confirmation}
                    onChange={(e) => setConfirmation(e.target.value)}
                    required
                  />
                </div>
              )}
              <button type="submit" className="public-button auth-submit">
                {submitting ? (
                  <>
                    <Loader2 size={18} className="animate-spin" />
                    {isSignup ? "Creating your account…" : "Signing in…"}
                  </>
                ) : (
                  <>
                    {isSignup ? "Create account" : "Sign in"}
                    <ArrowRight size={17} />
                  </>
                )}
              </button>
            </fieldset>
          </form>
          <p className="auth-switch">
            {isSignup ? "Already have an account?" : "New to DevOps?"}{" "}
            <Link to={isSignup ? "/login" : "/signup"} state={location.state}>
              {isSignup ? "Sign in" : "Create an account"}
              <ArrowRight size={14} />
            </Link>
          </p>
          <p className="auth-assurance">
            <ShieldCheck size={16} />
            {isSignup
              ? "Your own work. Your own workspace."
              : "Your access is managed securely by your account."}
          </p>
        </section>
      </main>
      <footer className="auth-footer public-container">
        <span>AI-assisted. Human-approved.</span>
        <span>© {new Date().getFullYear()} DevOps</span>
      </footer>
    </div>
  );
}
