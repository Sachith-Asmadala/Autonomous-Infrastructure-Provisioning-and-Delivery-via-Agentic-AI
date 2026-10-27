import { create } from "zustand";
import type { AgentToolStep, Message } from "@/types";

export type { Message, AgentToolStep };

interface ChatState {
  messages: Message[];
  sessionId: string | null;
  isLoading: boolean;
  addMessage: (msg: Message) => void;
  updateMessage: (id: string, patch: Partial<Message>) => void;
  appendMessageContent: (id: string, chunk: string) => void;
  setLoading: (v: boolean) => void;
  setSessionId: (id: string | null) => void;
  clearMessages: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  sessionId: null,
  isLoading: false,
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  updateMessage: (id, patch) =>
    set((s) => ({
      messages: s.messages.map((msg) =>
        msg.id === id ? { ...msg, ...patch } : msg,
      ),
    })),
  appendMessageContent: (id, chunk) =>
    set((s) => ({
      messages: s.messages.map((msg) =>
        msg.id === id ? { ...msg, content: `${msg.content}${chunk}` } : msg,
      ),
    })),
  setLoading: (v) => set({ isLoading: v }),
  setSessionId: (id) => set({ sessionId: id }),
  clearMessages: () => set({ messages: [], sessionId: null, isLoading: false }),
}));
