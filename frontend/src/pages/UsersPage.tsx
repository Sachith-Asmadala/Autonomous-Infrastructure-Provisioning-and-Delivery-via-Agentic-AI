import { useCallback, useEffect, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Link } from "react-router-dom";
import {
  AlertCircle,
  ArrowUpRight,
  CheckCircle2,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  UserCheck,
  UserX,
  UsersRound,
  X,
} from "lucide-react";
import { format } from "date-fns";
import clsx from "clsx";
import {
  approvalService,
  authService,
  type UserStatusApproval,
} from "@/services/api";
import { ROLE_DEFINITIONS, ROLE_ORDER } from "@/lib/rbac";
import { getUserFriendlyError } from "@/lib/errorMessages";
import { useAuthStore } from "@/store/authStore";
import { CreateUserDialog } from "@/components/users/CreateUserDialog";
import type { User, UserRole } from "@/types";

function joinedDate(value?: string) {
  if (!value || Number.isNaN(new Date(value).getTime()))
    return "Date unavailable";
  return format(new Date(value), "MMM d, yyyy");
}

export default function UsersPage() {
  const currentUser = useAuthStore((state) => state.user);
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState<UserRole | "all">("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [createOpen, setCreateOpen] = useState(false);
  const [requestingId, setRequestingId] = useState<string | null>(null);
  const [review, setReview] = useState<UserStatusApproval | null>(null);
  const [deciding, setDeciding] = useState(false);
  const [reviewError, setReviewError] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const requestId = useRef(0);

  const fetchUsers = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    setError("");
    try {
      const data = await authService.listUsers();
      if (id === requestId.current) {
        setUsers(data);
        setLoaded(true);
      }
    } catch (err: unknown) {
      if (id === requestId.current) {
        setUsers([]);
        setLoaded(false);
        setError(getUserFriendlyError(err));
      }
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    void fetchUsers();
    return () => {
      requestId.current++;
    };
  }, [fetchUsers]);

  const requestChange = async (user: User) => {
    if (requestingId) return;
    setRequestingId(user.id);
    setError("");
    setSuccess("");
    setReviewError("");
    try {
      setReview(
        await authService.requestUserStatusChange(
          user.id,
          user.is_active === false,
        ),
      );
    } catch (err: unknown) {
      setError(getUserFriendlyError(err));
    } finally {
      setRequestingId(null);
    }
  };

  const decide = async (approved: boolean) => {
    if (!review || deciding) return;
    setDeciding(true);
    setReviewError("");
    try {
      const result = await approvalService.decide(review.approval_id, approved);
      if (approved && result.execution_status !== "completed")
        throw new Error(
          "The account change could not be completed. Check the audit log.",
        );
      setSuccess(
        approved
          ? `${review.user.username} is now ${review.is_active ? "active" : "inactive"}.${review.is_active ? " They can sign in again." : " Existing sessions have been revoked."}`
          : `Account change for ${review.user.username} was cancelled.`,
      );
      setReview(null);
      await fetchUsers();
    } catch (err: unknown) {
      setReviewError(getUserFriendlyError(err));
    } finally {
      setDeciding(false);
    }
  };

  const activeCount = users.filter((user) => user.is_active !== false).length;
  const inactiveCount = users.length - activeCount;
  const activeAdmins = users.filter(
    (user) => user.role === "admin" && user.is_active !== false,
  ).length;
  const filteredUsers = users.filter(
    (user) =>
      `${user.username} ${user.email || ""}`
        .toLowerCase()
        .includes(query.trim().toLowerCase()) &&
      (roleFilter === "all" || user.role === roleFilter) &&
      (statusFilter === "all" ||
        (user.is_active !== false ? "active" : "inactive") === statusFilter),
  );
  const metrics = [
    {
      label: "Total members",
      value: users.length,
      detail: "Accounts in your workspace",
      icon: UsersRound,
    },
    {
      label: "Active accounts",
      value: activeCount,
      detail: "Can sign in and use their tools",
      icon: UserCheck,
    },
    {
      label: "Inactive accounts",
      value: inactiveCount,
      detail: "Workspace access suspended",
      icon: UserX,
    },
    {
      label: "Administrators",
      value: users.filter((user) => user.role === "admin").length,
      detail: `${activeAdmins} active · manage workspace access`,
      icon: ShieldCheck,
    },
  ];

  return (
    <div className="h-full overflow-y-auto bg-surface-900">
      <div className="mx-auto max-w-[1440px] space-y-6 px-4 py-6 md:px-8 md:py-8">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.15em] text-primary-700 dark:text-primary-300">
              Workspace administration
            </p>
            <h1 className="text-2xl font-semibold tracking-tight text-ink">
              Members & access
            </h1>
            <p className="mt-2 text-sm text-ink-subtle">
              Manage who can access your workspace and keep every account change
              accountable.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={fetchUsers}
              disabled={loading}
              className="btn-secondary"
            >
              <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
              Refresh
            </button>
            <button
              type="button"
              onClick={() => setCreateOpen(true)}
              className="btn-primary"
            >
              <Plus size={16} />
              Add member
            </button>
          </div>
        </header>
        {error && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-700 dark:text-red-200"
          >
            <AlertCircle size={18} className="shrink-0" />
            {error}
          </div>
        )}
        {success && (
          <div
            role="status"
            className="flex items-start gap-2 rounded-lg border border-primary-500/30 bg-primary-500/10 p-4 text-sm text-primary-700 dark:text-primary-200"
          >
            <CheckCircle2 size={18} className="shrink-0" />
            <span className="flex-1">{success}</span>
            <button
              type="button"
              aria-label="Dismiss notification"
              onClick={() => setSuccess("")}
            >
              <X size={16} />
            </button>
          </div>
        )}
        <section
          aria-label="Member statistics"
          className="grid grid-cols-2 gap-3 xl:grid-cols-4"
        >
          {metrics.map(({ label, value, detail, icon: Icon }) => (
            <div key={label} className="card p-5">
              <div className="flex items-center justify-between">
                <h2 className="text-xs font-medium text-ink-subtle">{label}</h2>
                <Icon
                  size={18}
                  className="text-primary-600 dark:text-primary-300"
                />
              </div>
              <p className="mt-3 text-3xl font-semibold text-ink">
                {loading ? "…" : loaded ? value : "—"}
              </p>
              <p className="mt-2 text-[11px] text-ink-subtle">{detail}</p>
            </div>
          ))}
        </section>
        <section className="card overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-surface-600 px-5 py-4">
            <div>
              <h2 className="text-sm font-semibold text-ink">
                Member directory
              </h2>
              <p className="mt-1 text-xs text-ink-subtle">
                Account roles, status, and access controls
              </p>
            </div>
            <Link to="/executions" className="btn-ghost text-xs">
              View account activity <ArrowUpRight size={14} />
            </Link>
          </div>
          <div className="flex flex-col gap-3 border-b border-surface-600 bg-surface-900/40 p-4 sm:flex-row">
            <div className="relative min-w-0 flex-1">
              <Search
                size={16}
                className="pointer-events-none absolute left-3 top-3 text-ink-subtle"
              />
              <input
                aria-label="Search members"
                placeholder="Search by name or email…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="input-field py-2.5 pl-10 pr-3"
              />
            </div>
            <select
              aria-label="Filter members by role"
              value={roleFilter}
              onChange={(event) =>
                setRoleFilter(event.target.value as UserRole | "all")
              }
              className="input-field px-3 py-2.5 sm:w-40"
            >
              <option value="all">All roles</option>
              {ROLE_ORDER.map((role) => (
                <option key={role} value={role}>
                  {ROLE_DEFINITIONS[role].label}
                </option>
              ))}
            </select>
            <select
              aria-label="Filter members by status"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
              className="input-field px-3 py-2.5 sm:w-40"
            >
              <option value="all">All statuses</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
          </div>
          {loading ? (
            <div role="status" className="space-y-3 p-5">
              <span className="sr-only">Loading members</span>
              {[1, 2, 3].map((value) => (
                <div
                  key={value}
                  className="h-16 animate-pulse rounded-lg bg-surface-700"
                />
              ))}
            </div>
          ) : error && !loaded ? (
            <div className="p-10 text-center text-sm text-ink-subtle">
              The directory is unavailable. Refresh to try again.
            </div>
          ) : filteredUsers.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="hidden bg-surface-900/50 text-[11px] font-medium text-ink-subtle md:table-header-group">
                  <tr>
                    <th className="px-5 py-3 font-medium">Member</th>
                    <th className="px-4 py-3 font-medium">Role</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium">Joined</th>
                    <th className="px-5 py-3 text-right font-medium">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-600">
                  {filteredUsers.map((user) => {
                    const role = ROLE_DEFINITIONS[user.role];
                    const active = user.is_active !== false;
                    const isSelf = user.id === currentUser?.id;
                    const blocked =
                      active &&
                      (isSelf || (user.role === "admin" && activeAdmins <= 1));
                    return (
                      <tr
                        key={user.id}
                        className="flex flex-wrap items-center gap-y-3 px-5 py-4 transition hover:bg-surface-900/60 md:table-row md:p-0"
                      >
                        <td className="w-full md:w-auto md:px-5 md:py-4">
                          <div className="flex items-center gap-3">
                            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-700 text-xs font-semibold text-ink-muted">
                              {user.username.slice(0, 2).toUpperCase()}
                            </span>
                            <div className="min-w-0">
                              <p className="break-all text-sm font-semibold text-ink">
                                {user.username}
                                {isSelf && (
                                  <span className="ml-2 text-[10px] font-normal text-ink-subtle">
                                    You
                                  </span>
                                )}
                              </p>
                              <p className="mt-0.5 break-all text-xs text-ink-subtle">
                                {user.email}
                              </p>
                            </div>
                          </div>
                        </td>
                        <td className="pr-3 md:px-4 md:py-4">
                          <span
                            className={clsx(
                              "inline-flex rounded-md border px-2 py-0.5 text-[11px] font-medium",
                              role.badgeClass,
                            )}
                          >
                            {role.label}
                          </span>
                        </td>
                        <td className="pr-3 md:px-4 md:py-4">
                          <span
                            className={
                              active ? "badge-success" : "badge-warning"
                            }
                          >
                            <span
                              className={clsx(
                                "mr-1.5 h-1.5 w-1.5 rounded-full",
                                active ? "bg-primary-500" : "bg-amber-500",
                              )}
                            />
                            {active ? "Active" : "Inactive"}
                          </span>
                        </td>
                        <td className="hidden px-4 py-4 text-xs text-ink-subtle md:table-cell">
                          {joinedDate(user.created_at)}
                        </td>
                        <td className="ml-auto md:px-5 md:py-4 md:text-right">
                          <button
                            type="button"
                            onClick={() => requestChange(user)}
                            disabled={blocked || requestingId !== null}
                            title={
                              blocked
                                ? isSelf
                                  ? "You cannot deactivate your own account"
                                  : "At least one active administrator must remain"
                                : undefined
                            }
                            aria-label={`${active ? "Deactivate" : "Activate"} ${user.username}`}
                            className={clsx(
                              "inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border px-3 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-40",
                              active
                                ? "border-surface-600 text-ink-muted hover:border-red-500/40 hover:bg-red-500/5 hover:text-red-600 dark:hover:text-red-300"
                                : "border-primary-500/30 bg-primary-500/5 text-primary-700 hover:bg-primary-500/10 dark:text-primary-300",
                            )}
                          >
                            {requestingId === user.id ? (
                              <Loader2 size={14} className="animate-spin" />
                            ) : active ? (
                              <UserX size={14} />
                            ) : (
                              <UserCheck size={14} />
                            )}{" "}
                            {active ? "Deactivate" : "Activate"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="flex flex-col items-center px-6 py-12 text-center">
              <UsersRound size={30} className="mb-3 text-ink-faint" />
              <h3 className="text-sm font-medium text-ink">
                {users.length ? "No matching members" : "No members found"}
              </h3>
              <p className="mt-1 text-xs text-ink-subtle">
                {users.length
                  ? "Try a different name, role, or status filter."
                  : "Add a member to get started."}
              </p>
              {users.length > 0 && (
                <button
                  type="button"
                  onClick={() => {
                    setQuery("");
                    setRoleFilter("all");
                    setStatusFilter("all");
                  }}
                  className="btn-ghost mt-3 text-xs"
                >
                  Clear filters
                </button>
              )}
            </div>
          )}
          <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-surface-600 px-5 py-3 text-[11px] text-ink-subtle">
            <span>
              {loaded
                ? `${filteredUsers.length} of ${users.length} members`
                : "Member directory"}
            </span>
            <span className="flex items-center gap-1.5">
              <ShieldCheck size={13} />
              Status changes require admin approval
            </span>
          </footer>
        </section>
        <div className="flex items-start gap-3 rounded-xl border border-surface-600 bg-surface-800/50 p-4">
          <ShieldCheck
            size={18}
            className="mt-0.5 shrink-0 text-primary-600 dark:text-primary-300"
          />
          <p className="text-xs leading-6 text-ink-subtle">
            Deactivating an account blocks sign-in and revokes its sessions.
            Reactivating restores access with a fresh sign-in. Account history
            remains available in the audit log.
          </p>
        </div>
      </div>
      {createOpen && (
        <CreateUserDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          onCreated={(user) => {
            setUsers((current) => [user, ...current]);
            setLoaded(true);
            setSuccess(
              `${user.username} was added as ${ROLE_DEFINITIONS[user.role].label}.`,
            );
          }}
        />
      )}
      <Dialog.Root
        open={review !== null}
        onOpenChange={(open) => {
          if (!open && !deciding) setReview(null);
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/50 backdrop-blur-sm" />
          <Dialog.Content
            onEscapeKeyDown={(event) => {
              if (deciding) event.preventDefault();
            }}
            onInteractOutside={(event) => {
              if (deciding) event.preventDefault();
            }}
            className="fixed left-1/2 top-1/2 z-50 max-h-[90dvh] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl border border-surface-600 bg-surface-800 p-6 shadow-xl"
          >
            <div className="mb-4 flex items-center justify-between">
              <span className="badge-warning">High risk · Admin review</span>
              <Dialog.Close
                disabled={deciding}
                aria-label="Close account change review"
                className="btn-ghost p-2"
              >
                <X size={18} />
              </Dialog.Close>
            </div>
            <Dialog.Title className="break-words text-xl font-semibold text-ink">
              {review?.is_active ? "Activate" : "Deactivate"}{" "}
              {review?.user.username}?
            </Dialog.Title>
            <Dialog.Description className="mt-2 text-sm leading-6 text-ink-subtle">
              {review?.is_active
                ? "This member can sign in again with their existing credentials. Previously revoked sessions remain invalid."
                : "This member will lose workspace access. Their current sessions will be revoked, and their activity history will be preserved."}
            </Dialog.Description>
            <dl className="my-5 space-y-2 rounded-lg border border-surface-600 bg-surface-900 p-4 text-xs">
              <div className="flex justify-between gap-3">
                <dt className="text-ink-subtle">Account</dt>
                <dd className="break-all text-right font-medium text-ink">
                  {review?.user.email}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-subtle">Role</dt>
                <dd className="text-ink">
                  {review && ROLE_DEFINITIONS[review.user.role].label}
                </dd>
              </div>
            </dl>
            {reviewError && (
              <p
                role="alert"
                className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-700 dark:text-red-200"
              >
                {reviewError}
              </p>
            )}
            <p className="mb-5 text-[11px] leading-5 text-ink-subtle">
              The approval request has been saved. Closing this review leaves it
              pending in the approval queue.
            </p>
            <div className="flex flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={() => decide(false)}
                disabled={deciding}
                className="btn-secondary"
              >
                Reject change
              </button>
              <button
                type="button"
                onClick={() => decide(true)}
                disabled={deciding}
                className={clsx(
                  "btn-primary",
                  !review?.is_active && "bg-red-600 hover:bg-red-500",
                )}
              >
                {deciding && <Loader2 size={15} className="animate-spin" />}
                Approve {review?.is_active ? "activation" : "deactivation"}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
