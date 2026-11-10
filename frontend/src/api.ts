import type { Conversation, ConversationSummary, QueryResponse } from "./types";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

/** Error that also carries the conversation id the server stored the failed turn under. */
export class ChatError extends Error {
  conversationId: string | null;
  constructor(message: string, conversationId: string | null) {
    super(message);
    this.conversationId = conversationId;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ChatError(
      typeof err.detail === "string" ? err.detail : "Unknown error",
      err.conversation_id ?? null,
    );
  }
  return res.json();
}

export const sendChat = (message: string, conversationId: string | null) =>
  request<QueryResponse>("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, conversation_id: conversationId }),
  });

export const listConversations = () => request<ConversationSummary[]>("/api/conversations");

export const getConversation = (id: string) => request<Conversation>(`/api/conversations/${id}`);

export const deleteConversation = (id: string) =>
  request<{ status: string }>(`/api/conversations/${id}`, { method: "DELETE" });
