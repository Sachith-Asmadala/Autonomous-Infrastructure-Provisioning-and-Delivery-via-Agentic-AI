import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemeMode = "light" | "dark" | "system";
type ResolvedTheme = "light" | "dark";

interface ThemeState {
  theme: ThemeMode;
  resolvedTheme: ResolvedTheme;
  setTheme: (theme: ThemeMode) => void;
  toggleTheme: () => void;
  syncSystemTheme: () => void;
}

const THEME_STORAGE_KEY = "devops-assistant-theme";

export function resolveTheme(theme: ThemeMode): ResolvedTheme {
  if (theme !== "system") return theme;
  if (typeof window === "undefined") return "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function applyTheme(theme: ThemeMode) {
  if (typeof document === "undefined") return "dark";
  const resolved = resolveTheme(theme);
  const root = document.documentElement;
  root.classList.toggle("dark", resolved === "dark");
  root.dataset.theme = resolved;
  return resolved;
}

export function applyInitialTheme() {
  if (typeof window === "undefined") return;
  try {
    const raw = window.localStorage.getItem(THEME_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    const savedTheme = parsed?.state?.theme as ThemeMode | undefined;
    applyTheme(savedTheme || "light");
  } catch {
    applyTheme("light");
  }
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      theme: "light",
      resolvedTheme: "light",
      setTheme: (theme) => {
        const resolvedTheme = applyTheme(theme);
        set({ theme, resolvedTheme });
      },
      toggleTheme: () => {
        const current = get().resolvedTheme;
        const nextTheme: ThemeMode = current === "dark" ? "light" : "dark";
        const resolvedTheme = applyTheme(nextTheme);
        set({ theme: nextTheme, resolvedTheme });
      },
      syncSystemTheme: () => {
        const { theme } = get();
        const resolvedTheme = applyTheme(theme);
        set({ resolvedTheme });
      },
    }),
    {
      name: THEME_STORAGE_KEY,
      partialize: (state) => ({ theme: state.theme }),
      onRehydrateStorage: () => (state) => {
        if (state) state.resolvedTheme = applyTheme(state.theme);
      },
    },
  ),
);
