import { create } from "zustand";
import { IS_AUTH_DISABLED, LOCAL_USER } from "@/config/runtime";
import { authService } from "@/services/api";
import { useChatStore } from "@/store/chatStore";
import type { User } from "@/types";

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  checkAuth: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  markUnauthenticated: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: IS_AUTH_DISABLED ? LOCAL_USER : null,
  isAuthenticated: IS_AUTH_DISABLED,
  isLoading: !IS_AUTH_DISABLED,

  checkAuth: async () => {
    if (IS_AUTH_DISABLED) {
      set({ user: LOCAL_USER, isAuthenticated: true, isLoading: false });
      return;
    }
    set({ isLoading: true });
    try {
      const user = await authService.me();
      set({ user, isAuthenticated: true, isLoading: false });
    } catch {
      set({ user: null, isAuthenticated: false, isLoading: false });
    }
  },

  login: async (email, password) => {
    if (IS_AUTH_DISABLED) {
      set({ user: LOCAL_USER, isAuthenticated: true, isLoading: false });
      return;
    }
    set({ isLoading: true });
    try {
      const user = await authService.login(email, password);
      set({ user, isAuthenticated: true, isLoading: false });
    } catch (error) {
      set({ user: null, isAuthenticated: false, isLoading: false });
      throw error;
    }
  },

  signup: async (email, username, password) => {
    if (IS_AUTH_DISABLED) {
      set({ user: LOCAL_USER, isAuthenticated: true, isLoading: false });
      return;
    }
    set({ isLoading: true });
    try {
      const user = await authService.register({
        email,
        username,
        password,
      });
      set({ user, isAuthenticated: true, isLoading: false });
    } catch (error) {
      set({ user: null, isAuthenticated: false, isLoading: false });
      throw error;
    }
  },

  logout: async () => {
    if (IS_AUTH_DISABLED) {
      set({ user: LOCAL_USER, isAuthenticated: true, isLoading: false });
      return;
    }
    try {
      await authService.logout();
    } finally {
      set({ user: null, isAuthenticated: false, isLoading: false });
    }
  },

  markUnauthenticated: () =>
    IS_AUTH_DISABLED
      ? set({ user: LOCAL_USER, isAuthenticated: true, isLoading: false })
      : set({ user: null, isAuthenticated: false, isLoading: false }),
}));

// Clear local conversation state when a session ends or a different member
// signs in on the same browser. Server memory is scoped to the account too.
useAuthStore.subscribe((state, previous) => {
  if (
    state.user?.id !== previous.user?.id ||
    state.user?.role !== previous.user?.role
  ) {
    useChatStore.getState().clearMessages();
  }
});
