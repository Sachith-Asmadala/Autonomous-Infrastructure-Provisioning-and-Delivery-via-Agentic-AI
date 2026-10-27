import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import {
  ArrowUpRight,
  ChevronRight,
  Command,
  GitBranch,
  LogOut,
  Menu,
  Search,
  ShieldCheck,
  WifiOff,
  X,
} from "lucide-react";
import clsx from "clsx";
import { useAuthStore } from "@/store/authStore";
import { IS_AUTH_DISABLED, IS_MOBILE_MODE } from "@/config/runtime";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { getRoleDefinition, hasPermission } from "@/lib/rbac";
import { navigation } from "./navigation";

export default function Layout() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const role = getRoleDefinition(user?.role);
  const visibleItems = navigation.filter(
    (item) =>
      !((IS_AUTH_DISABLED || IS_MOBILE_MODE) && item.webOnly) &&
      (IS_AUTH_DISABLED || hasPermission(user?.role, item.permission)),
  );
  const current = visibleItems.find((item) => item.to === location.pathname);
  const results = visibleItems.filter((item) =>
    `${item.label} ${item.group}`
      .toLowerCase()
      .includes(query.trim().toLowerCase()),
  );

  useEffect(() => {
    const online = () => setIsOnline(navigator.onLine);
    const shortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen((open) => !open);
      }
    };
    window.addEventListener("online", online);
    window.addEventListener("offline", online);
    window.addEventListener("keydown", shortcut);
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", online);
      window.removeEventListener("keydown", shortcut);
    };
  }, []);

  useEffect(() => {
    setMenuOpen(false);
    setSearchOpen(false);
  }, [location.pathname]);

  const handleLogout = async () => {
    try {
      await logout();
    } finally {
      navigate("/login", { replace: true });
    }
  };

  const sidebar = (
    <div className="workspace-sidebar flex h-full min-h-0 flex-col">
      <NavLink
        to="/dashboard"
        className="flex items-center gap-3 px-6 pb-7 pt-8"
        onClick={() => setMenuOpen(false)}
        aria-label="DevOps overview"
      >
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-400 text-slate-950">
          <GitBranch size={23} strokeWidth={2.4} />
        </span>
        <span>
          <span className="block text-xl font-semibold tracking-tight text-white">
            DevOps<span className="text-emerald-400">.</span>
          </span>
          <span className="text-[10px] font-medium uppercase tracking-[0.22em] text-slate-400">
            AI workspace
          </span>
        </span>
      </NavLink>
      <div className="mx-4 mb-5 flex items-center gap-3 rounded-lg border border-white/10 bg-white/[0.04] p-3">
        <span className="flex h-8 w-8 items-center justify-center rounded-md bg-white/10 text-xs font-semibold text-slate-200">
          SD
        </span>
        <div>
          <p className="text-xs font-medium text-slate-100">Smart delivery</p>
          <p className="mt-0.5 text-[11px] text-slate-400">
            Your DevOps workspace
          </p>
        </div>
      </div>
      <nav
        aria-label="Main navigation"
        className="min-h-0 flex-1 space-y-5 overflow-y-auto px-3 pb-5"
      >
        {[...new Set(visibleItems.map((item) => item.group))].map((group) => (
          <div key={group}>
            <p className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
              {group}
            </p>
            <div className="space-y-1">
              {visibleItems
                .filter((item) => item.group === group)
                .map(({ to, icon: Icon, label }) => (
                  <NavLink
                    key={to}
                    to={to}
                    onClick={() => setMenuOpen(false)}
                    className={({ isActive }) =>
                      clsx("sidebar-link", isActive && "sidebar-link-active")
                    }
                  >
                    <Icon size={17} strokeWidth={1.8} />
                    <span className="flex-1">{label}</span>
                    <ChevronRight size={13} className="nav-chevron" />
                  </NavLink>
                ))}
            </div>
          </div>
        ))}
      </nav>
      <div className="mx-4 mb-4 rounded-lg border border-emerald-400/15 bg-emerald-400/5 p-3">
        <div className="flex items-center gap-2 text-xs font-medium text-emerald-300">
          <ShieldCheck size={15} /> Human oversight, built in
        </div>
        <p className="mt-1.5 text-[11px] leading-5 text-slate-400">
          High-risk actions go through approval before execution.
        </p>
      </div>
      <div className="flex items-center gap-3 border-t border-white/10 px-5 py-4">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-700 text-xs font-semibold text-white">
          {(user?.username || "User").slice(0, 2).toUpperCase()}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-slate-100">
            {user?.username || "Workspace user"}
          </p>
          <p className="mt-0.5 text-[11px] text-slate-400">
            {IS_AUTH_DISABLED ? "Local workspace" : role.label}
          </p>
        </div>
        {!IS_AUTH_DISABLED && (
          <button
            type="button"
            onClick={handleLogout}
            aria-label="Sign out"
            title="Sign out"
            className="rounded-md p-2 text-slate-400 transition hover:bg-white/10 hover:text-white"
          >
            <LogOut size={16} />
          </button>
        )}
      </div>
    </div>
  );

  return (
    <div className="app-shell flex min-w-0 overflow-hidden app-bg">
      <a href="#workspace-content" className="skip-link">
        Skip to content
      </a>
      {!IS_MOBILE_MODE && (
        <aside className="hidden w-[248px] shrink-0 lg:block">{sidebar}</aside>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="workspace-topbar flex min-h-16 shrink-0 items-center justify-between gap-3 border-b border-surface-600 bg-surface-800 px-4 md:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <Dialog.Root open={menuOpen} onOpenChange={setMenuOpen}>
              <Dialog.Trigger asChild>
                <button
                  className={clsx(
                    "btn-ghost p-2",
                    !IS_MOBILE_MODE && "lg:hidden",
                  )}
                  aria-label="Open navigation"
                >
                  <Menu size={20} />
                </button>
              </Dialog.Trigger>
              <Dialog.Portal>
                <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-sm" />
                <Dialog.Content className="fixed inset-y-0 left-0 z-50 w-[min(300px,88vw)] outline-none">
                  <Dialog.Title className="sr-only">
                    Workspace navigation
                  </Dialog.Title>
                  <Dialog.Description className="sr-only">
                    Navigate your DevOps tools and account.
                  </Dialog.Description>
                  <Dialog.Close
                    className="absolute right-3 top-3 rounded-md p-2 text-slate-400 hover:bg-white/10"
                    aria-label="Close navigation"
                  >
                    <X size={17} />
                  </Dialog.Close>
                  {sidebar}
                </Dialog.Content>
              </Dialog.Portal>
            </Dialog.Root>
            <span className="hidden text-xs text-ink-subtle sm:inline">
              Workspace
            </span>
            <ChevronRight
              size={13}
              className="hidden text-ink-faint sm:inline"
            />
            <span className="truncate text-sm font-medium text-ink">
              {current?.label || "DevOps"}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-2 sm:gap-4">
            <button
              type="button"
              onClick={() => {
                setQuery("");
                setSearchOpen(true);
              }}
              className="flex items-center gap-2 rounded-lg border border-surface-600 px-2.5 py-2 text-xs text-ink-subtle transition hover:bg-surface-700 sm:w-56"
              aria-label="Search workspace"
            >
              <Search size={15} />
              <span className="hidden sm:inline">Go to a page…</span>
              <kbd className="ml-auto hidden items-center gap-0.5 rounded border border-surface-600 px-1 py-0.5 text-[10px] sm:flex">
                <Command size={10} /> K
              </kbd>
            </button>
            <ThemeToggle compact />
            <span
              className={clsx(
                "hidden rounded-md border px-2 py-1 text-[11px] font-medium md:inline-flex",
                role.badgeClass,
              )}
            >
              {role.label}
            </span>
          </div>
        </header>
        {!isOnline && (
          <div
            role="status"
            className="flex items-center gap-2 border-b border-amber-500/30 bg-amber-500/10 px-5 py-2 text-xs text-amber-700 dark:text-amber-200"
          >
            <WifiOff size={14} />
            You’re offline. Reconnect to load data and run actions.
          </div>
        )}
        <main
          id="workspace-content"
          tabIndex={-1}
          className="workspace-content min-h-0 min-w-0 flex-1 overflow-hidden outline-none"
        >
          <Outlet />
        </main>
      </div>
      <Dialog.Root open={searchOpen} onOpenChange={setSearchOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/50 backdrop-blur-sm" />
          <Dialog.Content className="fixed left-1/2 top-[15%] z-50 w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 overflow-hidden rounded-xl border border-surface-600 bg-surface-800 shadow-xl">
            <Dialog.Title className="sr-only">Search workspace</Dialog.Title>
            <Dialog.Description className="sr-only">
              Find a page available to your role.
            </Dialog.Description>
            <div className="flex items-center gap-3 border-b border-surface-600 px-4">
              <Search size={18} className="text-ink-subtle" />
              <input
                aria-label="Find a page"
                placeholder="Where would you like to go?"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="min-w-0 flex-1 bg-transparent py-5 text-sm outline-none"
              />
              <Dialog.Close aria-label="Close search" className="btn-ghost p-1">
                <X size={16} />
              </Dialog.Close>
            </div>
            <div className="max-h-[55dvh] overflow-y-auto p-2">
              {results.length ? (
                results.map(({ to, icon: Icon, label, group }) => (
                  <button
                    key={to}
                    onClick={() => {
                      navigate(to);
                      setSearchOpen(false);
                    }}
                    className="flex w-full items-center gap-3 rounded-lg px-3 py-3 text-left text-sm text-ink-muted hover:bg-surface-700"
                  >
                    <Icon size={17} />
                    <span className="flex-1">{label}</span>
                    <span className="text-[11px] text-ink-subtle">{group}</span>
                    <ArrowUpRight size={14} />
                  </button>
                ))
              ) : (
                <p className="px-4 py-10 text-center text-sm text-ink-subtle">
                  No pages found. Try “chat” or “settings”.
                </p>
              )}
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
