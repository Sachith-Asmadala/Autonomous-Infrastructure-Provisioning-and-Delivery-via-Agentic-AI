import {
  ArrowDown,
  ArrowRight,
  Check,
  CheckCheck,
  GitBranch,
  GitPullRequest,
  ScanLine,
  ShieldCheck,
} from "lucide-react";
import { Link } from "react-router-dom";
import Brand from "@/components/public/Brand";
import { useAuthStore } from "@/store/authStore";
import "@/styles/public.css";

const steps = [
  {
    number: "01",
    icon: ScanLine,
    title: "Find the signal.",
    text: "Turn noisy build logs into a failure diagnosis and a practical next step.",
  },
  {
    number: "02",
    icon: GitBranch,
    title: "Shape the workflow.",
    text: "Understand your repository’s stack and generate a GitHub Actions workflow that fits.",
  },
  {
    number: "03",
    icon: ShieldCheck,
    title: "Keep the final say.",
    text: "Review proposed changes, approve eligible actions, and follow the audit trail.",
  },
];

export default function LandingPage() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const destination = isAuthenticated ? "/dashboard" : "/signup";
  return (
    <div className="public-page screen-scroll">
      <a className="public-skip" href="#main">
        Skip to content
      </a>
      <header className="public-nav public-container">
        <Brand />
        <nav aria-label="Main navigation">
          <a href="#workflow" className="public-nav-about">
            How it works
          </a>
          <Link
            to={isAuthenticated ? "/dashboard" : "/login"}
            className="public-nav-login"
          >
            {isAuthenticated ? "Workspace" : "Log in"}
          </Link>
          <Link to={destination} className="public-button public-button-small">
            {isAuthenticated ? "Open dashboard" : "Get started"}
            <ArrowRight size={15} />
          </Link>
        </nav>
      </header>
      <main id="main">
        <section
          className="public-hero public-container"
          aria-labelledby="hero-title"
        >
          <div className="public-hero-copy">
            <p className="public-eyebrow">
              <span className="public-status-dot" /> THE INTELLIGENT DELIVERY
              WORKSPACE
            </p>
            <h1 id="hero-title">
              Less friction.
              <br />
              More <span className="public-serif">forward.</span>
            </h1>
            <p className="public-intro">
              From a failed build to a clear next step. Bring diagnosis, CI/CD
              workflows, and human approval into one considered workspace.
            </p>
            <div className="public-hero-actions">
              <Link to={destination} className="public-button">
                {isAuthenticated
                  ? "Open your workspace"
                  : "Create your workspace"}
                <ArrowRight size={17} />
              </Link>
              <a href="#workflow" className="public-text-link">
                Explore the flow <ArrowDown size={15} />
              </a>
            </div>
            <p className="public-hero-note">
              <ShieldCheck size={15} /> AI-assisted. Human-approved.
            </p>
          </div>
          <div
            className="delivery-visual"
            aria-label="Illustrative delivery flow: diagnose a failed build, propose a fix, then wait for human approval"
          >
            <div className="delivery-ruler">
              <span>DELIVERY / IN FOCUS</span>
              <span>ILLUSTRATIVE FLOW</span>
            </div>
            <div className="delivery-track">
              <div className="delivery-event">
                <span className="delivery-node delivery-node-warning" />
                <span>Build needs attention</span>
                <span className="delivery-event-tag">CI</span>
              </div>
              <div className="delivery-diagnosis">
                <div className="delivery-card-heading">
                  <ScanLine size={18} />
                  <span>Clarity from the noise</span>
                  <span className="delivery-ai">AI</span>
                </div>
                <code>
                  <span>error</span> Missing script: “test”
                </code>
                <p>
                  The build is calling a test script that hasn’t been defined.
                </p>
                <div className="delivery-recommendation">
                  <Check size={15} />
                  <span>Add a test command to package.json</span>
                </div>
              </div>
              <div className="delivery-event">
                <span className="delivery-node" />
                <GitPullRequest size={17} />
                <span>Propose a change</span>
              </div>
              <div className="delivery-approval">
                <span className="delivery-approval-icon">
                  <ShieldCheck size={23} />
                </span>
                <div>
                  <strong>Your decision comes next.</strong>
                  <p>Awaiting human approval</p>
                </div>
                <span className="delivery-pending-dot" />
              </div>
            </div>
            <div className="delivery-footer">
              <CheckCheck size={14} />
              <span>A traceable path. At every step.</span>
              <span className="delivery-footer-line" />
            </div>
          </div>
        </section>
        <div className="public-principles public-container">
          <span>BUILT AROUND YOUR DELIVERY LOOP</span>
          <div>
            <span>GitHub Actions</span>
            <span>Failure diagnosis</span>
            <span>Human approval</span>
            <span>Audit history</span>
          </div>
        </div>
        <section
          id="workflow"
          className="public-workflow public-container"
          aria-labelledby="workflow-title"
        >
          <div className="public-section-heading">
            <p className="public-eyebrow">A CLEARER WAY THROUGH</p>
            <h2 id="workflow-title">
              From what happened
              <br />
              to <span className="public-serif">what’s next.</span>
            </h2>
            <p>
              Less context switching. A connected path from understanding the
              problem to reviewing the solution.
            </p>
          </div>
          <div className="public-steps">
            {steps.map(({ number, icon: Icon, title, text }) => (
              <article key={number}>
                <div className="public-step-top">
                  <span>{number}</span>
                  <Icon size={23} strokeWidth={1.5} />
                </div>
                <h3>{title}</h3>
                <p>{text}</p>
              </article>
            ))}
          </div>
        </section>
        <section
          className="public-control public-container"
          aria-labelledby="control-title"
        >
          <div className="public-control-symbol" aria-hidden="true">
            <ShieldCheck size={48} strokeWidth={1} />
          </div>
          <div>
            <p className="public-eyebrow">AUTOMATION WITH ACCOUNTABILITY</p>
            <h2 id="control-title">Move quickly. Stay in control.</h2>
            <p>
              Your workspace focuses on your work. Admins retain visibility
              across the team. Sensitive actions pass through an explicit
              approval, with a record of who requested and reviewed them.
            </p>
          </div>
          <Link to={destination} className="public-text-link">
            Start with clarity <ArrowRight size={17} />
          </Link>
        </section>
      </main>
      <footer className="public-footer public-container">
        <Brand />
        <p>Thoughtful automation. Confident delivery.</p>
        <span>© {new Date().getFullYear()} DevOps</span>
      </footer>
    </div>
  );
}
