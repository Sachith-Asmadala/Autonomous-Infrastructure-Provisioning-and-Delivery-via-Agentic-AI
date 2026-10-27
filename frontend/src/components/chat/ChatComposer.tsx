import { FormEvent, KeyboardEvent, useEffect, useRef } from "react";
import { SendHorizonal } from "lucide-react";

interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
}

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  disabled,
}: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, [value]);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      onSubmit();
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="shrink-0 border-t border-surface-600/80 bg-surface-900/85 px-3 py-3 backdrop-blur sm:px-4 sm:py-4 xl:px-6"
    >
      <div className="mx-auto flex max-w-5xl items-end gap-3 rounded-2xl border border-surface-600 bg-surface-800/90 p-2 shadow-panel focus-within:border-primary-500/70">
        <textarea
          aria-label="Message the DevOps assistant"
          ref={textareaRef}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about a failure, workflow, or next step…"
          rows={1}
          disabled={disabled}
          className="min-h-11 min-w-0 flex-1 resize-none bg-transparent px-3 py-3 text-sm text-ink outline-none placeholder:text-ink-faint disabled:cursor-not-allowed"
          style={{ maxHeight: "140px" }}
        />
        <button
          type="submit"
          disabled={disabled || !value.trim()}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary-600 text-white shadow-glow transition hover:bg-primary-500 disabled:cursor-not-allowed disabled:bg-surface-600 disabled:text-ink-faint disabled:shadow-none"
          aria-label="Send message"
        >
          <SendHorizonal size={17} />
        </button>
      </div>
      <p className="mt-2 hidden text-center text-xs text-ink-faint sm:block">
        High-risk infrastructure changes stay behind human approval controls.
      </p>
    </form>
  );
}
