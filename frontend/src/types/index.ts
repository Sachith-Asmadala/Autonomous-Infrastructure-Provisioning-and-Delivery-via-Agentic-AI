export type UserRole = "admin" | "developer";

export interface User {
  id: string;
  email?: string;
  username: string;
  role: UserRole;
  is_active?: boolean;
  created_at?: string;
}

export interface RoleProfile {
  role: UserRole;
  label: string;
  description: string;
  permissions: string[];
  can_self_signup: boolean;
}

export interface AgentToolStep {
  tool: string;
  input: unknown;
  output: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  steps?: AgentToolStep[];
  requiresApproval?: boolean;
  approvalId?: string;
  isStreaming?: boolean;
  error?: boolean;
}

export type ConnectionStatus =
  | "connecting"
  | "connected"
  | "disconnected"
  | "error";

export interface AgentDoneEvent {
  event: "done";
  session_id?: string;
}
export interface AgentErrorEvent {
  event: "error";
  detail?: string;
  message?: string;
}
export interface AgentPingEvent {
  event: "ping";
}
export type AgentWebSocketEvent =
  | AgentDoneEvent
  | AgentErrorEvent
  | AgentPingEvent;
