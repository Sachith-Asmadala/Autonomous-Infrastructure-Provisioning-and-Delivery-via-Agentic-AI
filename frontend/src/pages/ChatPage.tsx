import { useCallback, useEffect, useRef, useState } from "react";
import { Bot, ShieldCheck, Trash2 } from "lucide-react";
import { ChatComposer } from "@/components/chat/ChatComposer";
import { ChatEmptyState } from "@/components/chat/ChatEmptyState";
import { ConnectionStatusPill } from "@/components/chat/ConnectionStatusPill";
import { MessageBubble } from "@/components/chat/MessageBubble";
import { useAgentWebSocket } from "@/hooks/useAgentWebSocket";
import { agentService } from "@/services/api";
import { useChatStore } from "@/store/chatStore";
import { useAuthStore } from "@/store/authStore";
import { CHAT_SUGGESTIONS, getRoleDefinition } from "@/lib/rbac";

function createMessageId() {
  return (
    crypto.randomUUID?.() ||
    `${Date.now()}-${Math.random().toString(16).slice(2)}`
  );
}

export default function ChatPage() {
  const {
    messages,
    sessionId,
    isLoading,
    addMessage,
    appendMessageContent,
    updateMessage,
    setLoading,
    setSessionId,
    clearMessages,
  } = useChatStore();
  const { user } = useAuthStore();
  const role = getRoleDefinition(user?.role);
  const suggestions = CHAT_SUGGESTIONS[role.role];
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const activeAssistantIdRef = useRef<string | null>(null);

  const finishStreamingMessage = useCallback(() => {
    if (activeAssistantIdRef.current) {
      updateMessage(activeAssistantIdRef.current, { isStreaming: false });
      activeAssistantIdRef.current = null;
    }
    setLoading(false);
  }, [setLoading, updateMessage]);

  const {
    status,
    lastError,
    sendMessage: sendWsMessage,
    reconnect,
  } = useAgentWebSocket({
    sessionId,
    onToken: (token) => {
      if (activeAssistantIdRef.current)
        appendMessageContent(activeAssistantIdRef.current, token);
    },
    onDone: (wsSessionId) => {
      if (wsSessionId) setSessionId(wsSessionId);
      finishStreamingMessage();
    },
    onError: (message) => {
      if (activeAssistantIdRef.current) {
        updateMessage(activeAssistantIdRef.current, {
          content: `**Streaming error:** ${message}`,
          isStreaming: false,
          error: true,
        });
      } else {
        addMessage({
          id: createMessageId(),
          role: "assistant",
          content: `**Streaming error:** ${message}`,
          timestamp: new Date(),
          error: true,
        });
      }
      activeAssistantIdRef.current = null;
      setLoading(false);
    },
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isLoading]);

  const sendViaHttpFallback = useCallback(
    async (message: string, assistantId: string) => {
      const accountId = useAuthStore.getState().user?.id;
      try {
        const res = await agentService.chat(message, sessionId ?? undefined);
        if (useAuthStore.getState().user?.id !== accountId) return;
        if (res.session_id) setSessionId(res.session_id);
        updateMessage(assistantId, {
          content: res.output || "No response returned by the agent.",
          steps: res.intermediate_steps,
          requiresApproval: res.requires_approval,
          approvalId: res.approval_id,
          isStreaming: false,
        });
      } catch (err: any) {
        if (useAuthStore.getState().user?.id !== accountId) return;
        updateMessage(assistantId, {
          content: `**Request failed:** ${err.response?.data?.detail || err.message || "Something went wrong."}`,
          isStreaming: false,
          error: true,
        });
      } finally {
        if (useAuthStore.getState().user?.id === accountId) {
          activeAssistantIdRef.current = null;
          setLoading(false);
        }
      }
    },
    [sessionId, setLoading, setSessionId, updateMessage],
  );

  const sendMessage = useCallback(
    async (value?: string) => {
      const message = (value || input).trim();
      if (!message || isLoading) return;

      setInput("");
      const assistantId = createMessageId();
      activeAssistantIdRef.current = assistantId;

      addMessage({
        id: createMessageId(),
        role: "user",
        content: message,
        timestamp: new Date(),
      });
      addMessage({
        id: assistantId,
        role: "assistant",
        content: "",
        timestamp: new Date(),
        isStreaming: status === "connected",
      });
      setLoading(true);

      const sentOverSocket =
        status === "connected" && sendWsMessage({ message, sessionId });
      if (!sentOverSocket) {
        updateMessage(assistantId, {
          isStreaming: false,
          content: "_WebSocket unavailable. Using secure HTTP fallback…_",
        });
        await sendViaHttpFallback(message, assistantId);
      }
    },
    [
      addMessage,
      input,
      isLoading,
      sendViaHttpFallback,
      sendWsMessage,
      sessionId,
      setLoading,
      status,
      updateMessage,
    ],
  );

  const handleClear = async () => {
    const idToClear = sessionId;
    clearMessages();
    activeAssistantIdRef.current = null;
    setLoading(false);
    if (idToClear) {
      try {
        await agentService.clearSession(idToClear);
      } catch {
        /* local clear still succeeds */
      }
    }
  };

  return (
    <div className="flex h-full flex-col bg-surface-900">
      <div className="workspace-page-header shrink-0">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-primary-500/30 bg-primary-500/10 shadow-glow">
              <Bot
                size={22}
                className="text-primary-500 dark:text-primary-300"
              />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base font-semibold text-ink">Agent Chat</h1>
                <span
                  className={`hidden rounded-full border px-2 py-0.5 text-[11px] uppercase tracking-[0.18em] sm:inline-flex ${role.badgeClass}`}
                >
                  {role.label}
                </span>
              </div>
              <p className="mt-1 text-xs text-ink-subtle">
                {role.role === "admin"
                  ? "Full AI control plane with user and approval governance"
                  : "Developer AI workspace for diagnostics and staging workflows"}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <ConnectionStatusPill
              status={status}
              lastError={lastError}
              onReconnect={reconnect}
            />
            <div className="hidden items-center gap-1.5 rounded-full border border-surface-600 bg-surface-800 px-3 py-1.5 text-xs text-ink-muted sm:flex">
              <ShieldCheck
                size={13}
                className="text-primary-500 dark:text-primary-300"
              />
              Approval protected
            </div>
            {messages.length > 0 && (
              <button
                onClick={handleClear}
                className="flex items-center gap-1.5 rounded-full border border-surface-600 bg-surface-800 px-3 py-1.5 text-xs text-ink-muted transition hover:border-red-500/40 hover:text-red-500 dark:hover:text-red-300"
              >
                <Trash2 size={13} /> Clear
              </button>
            )}
          </div>
        </div>
      </div>
      <div className="relative flex-1 overflow-hidden">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(37,164,97,0.12),transparent_32rem),radial-gradient(circle_at_bottom_right,rgba(59,130,246,0.12),transparent_30rem)]" />
        <div className="relative h-full overflow-y-auto px-4 py-6 xl:px-6">
          <div className="mx-auto flex min-h-full max-w-5xl flex-col gap-5">
            {messages.length === 0 ? (
              <ChatEmptyState
                suggestions={suggestions}
                onSuggestion={sendMessage}
                disabled={isLoading}
              />
            ) : (
              messages.map((message) => (
                <MessageBubble key={message.id} msg={message} />
              ))
            )}
            <div ref={bottomRef} />
          </div>
        </div>
      </div>
      <ChatComposer
        value={input}
        onChange={setInput}
        onSubmit={() => sendMessage()}
        disabled={isLoading}
      />
    </div>
  );
}
