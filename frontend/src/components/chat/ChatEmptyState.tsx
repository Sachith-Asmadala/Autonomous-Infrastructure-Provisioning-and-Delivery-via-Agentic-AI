import {
  Bot,
  Container,
  GitBranch,
  HeartPulse,
  ServerCog,
  TerminalSquare,
} from "lucide-react";

const icons = [Container, HeartPulse, GitBranch, ServerCog, TerminalSquare];

interface ChatEmptyStateProps {
  suggestions: string[];
  onSuggestion: (value: string) => void;
  disabled?: boolean;
}

export function ChatEmptyState({
  suggestions,
  onSuggestion,
  disabled,
}: ChatEmptyStateProps) {
  return (
    <div className="flex min-h-full flex-col items-center justify-center px-3 py-8 text-center sm:px-4 sm:py-10">
      <div className="relative mb-7">
        <div className="absolute inset-0 rounded-3xl bg-primary-500/20 blur-2xl" />
        <div className="relative flex h-16 w-16 items-center justify-center rounded-3xl border border-primary-500/30 bg-primary-500/10 shadow-glow">
          <Bot size={32} className="text-primary-500 dark:text-primary-300" />
        </div>
      </div>
      <div className="max-w-xl">
        <p className="mb-3 text-xs font-semibold uppercase tracking-[0.3em] text-primary-700 dark:text-primary-300">
          Your AI delivery partner
        </p>
        <h2 className="text-xl font-semibold text-ink sm:text-2xl">
          What can we help you ship today?
        </h2>
        <p className="mt-3 text-sm leading-6 text-ink-muted">
          Understand a build failure, check your services, or plan your next
          delivery. Start with a suggestion below or ask in your own words.
        </p>
      </div>
      <div className="mt-7 grid w-full max-w-4xl grid-cols-1 gap-3 md:grid-cols-3">
        {suggestions.map((suggestion, index) => {
          const Icon = icons[index % icons.length];
          return (
            <button
              key={suggestion}
              onClick={() => onSuggestion(suggestion)}
              disabled={disabled}
              className="group rounded-2xl border border-surface-600 bg-surface-800/75 p-3 text-left shadow-panel transition-all hover:-translate-y-0.5 hover:border-primary-500/50 hover:bg-surface-700/80 disabled:cursor-not-allowed disabled:opacity-60 sm:p-4"
            >
              <div className="flex flex-col items-start gap-3">
                <div className="rounded-xl border border-surface-600 bg-surface-900 p-2 text-primary-600 transition-colors group-hover:border-primary-500/50 dark:text-primary-300">
                  <Icon size={17} />
                </div>
                <span className="text-sm font-medium leading-6 text-ink">
                  {suggestion}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
