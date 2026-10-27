import { useState, type FormEvent } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  AlertCircle,
  Eye,
  EyeOff,
  Loader2,
  Plus,
  ShieldCheck,
  X,
} from "lucide-react";
import { authService } from "@/services/api";
import { getUserFriendlyError } from "@/lib/errorMessages";
import type { User } from "@/types";

export function CreateUserDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (user: User) => void;
}) {
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting) return;
    if (
      !/^\S+@\S+\.\S+$/.test(email.trim()) ||
      username.trim().length < 3 ||
      password.length < 8
    ) {
      setError(
        "Enter a valid email, a username of at least 3 characters, and a password of at least 8 characters.",
      );
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const user = await authService.createUser({
        email: email.trim(),
        username: username.trim(),
        password,
        role: "developer",
      });
      onCreated(user);
      onOpenChange(false);
    } catch (err: unknown) {
      setError(getUserFriendlyError(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(value) => {
        if (!submitting) onOpenChange(value);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/50 backdrop-blur-sm" />
        <Dialog.Content
          onEscapeKeyDown={(event) => {
            if (submitting) event.preventDefault();
          }}
          onInteractOutside={(event) => {
            if (submitting) event.preventDefault();
          }}
          className="fixed left-1/2 top-1/2 z-50 max-h-[90dvh] w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl border border-surface-600 bg-surface-800 p-6 shadow-xl"
        >
          <div className="mb-4 flex items-center justify-between">
            <span className="rounded-xl bg-primary-500/10 p-3 text-primary-600 dark:text-primary-300">
              <ShieldCheck size={22} />
            </span>
            <Dialog.Close
              disabled={submitting}
              aria-label="Close new member form"
              className="btn-ghost p-2"
            >
              <X size={18} />
            </Dialog.Close>
          </div>
          <Dialog.Title className="text-xl font-semibold text-ink">
            Add a member
          </Dialog.Title>
          <Dialog.Description className="mt-2 text-sm leading-6 text-ink-subtle">
            Create a developer account with a personal workspace and access to
            its own work.
          </Dialog.Description>
          {error && (
            <div
              role="alert"
              className="mt-4 flex gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-700 dark:text-red-200"
            >
              <AlertCircle size={17} className="mt-0.5 shrink-0" />
              {error}
            </div>
          )}
          <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
            <fieldset disabled={submitting} className="space-y-4">
              <div>
                <label
                  htmlFor="member-email"
                  className="mb-1.5 block text-xs font-medium text-ink-muted"
                >
                  Email address
                </label>
                <input
                  id="member-email"
                  type="email"
                  autoComplete="off"
                  placeholder="member@example.com"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  className="input-field px-3 py-2.5"
                  required
                />
              </div>
              <div>
                <label
                  htmlFor="member-username"
                  className="mb-1.5 block text-xs font-medium text-ink-muted"
                >
                  Username
                </label>
                <input
                  id="member-username"
                  maxLength={50}
                  autoComplete="off"
                  placeholder="e.g. delivery.engineer"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  className="input-field px-3 py-2.5"
                  required
                />
              </div>
              <div>
                <label
                  htmlFor="member-password"
                  className="mb-1.5 block text-xs font-medium text-ink-muted"
                >
                  Initial password
                </label>
                <div className="relative">
                  <input
                    id="member-password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="new-password"
                    placeholder="At least 8 characters"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    className="input-field px-3 py-2.5 pr-12"
                    required
                  />
                  <button
                    type="button"
                    aria-label={
                      showPassword ? "Hide password" : "Show password"
                    }
                    onClick={() => setShowPassword((value) => !value)}
                    className="btn-ghost absolute right-1 top-1 p-2"
                  >
                    {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                  </button>
                </div>
              </div>
            </fieldset>
            <div className="flex justify-end gap-2 border-t border-surface-600 pt-4">
              <Dialog.Close disabled={submitting} className="btn-secondary">
                Cancel
              </Dialog.Close>
              <button
                type="submit"
                disabled={submitting}
                className="btn-primary"
              >
                {submitting ? (
                  <Loader2 size={15} className="animate-spin" />
                ) : (
                  <Plus size={15} />
                )}
                {submitting ? "Creating…" : "Create member"}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
