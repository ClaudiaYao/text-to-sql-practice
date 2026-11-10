export interface QueryResponse {
  answer: string;
  sql: string;
  columns: string[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  execution_ms: number;
  attempts: number;
  cached: boolean;
  complex: boolean;
  candidates: number;
  agreement: number | null;
  standalone_question: string;
  conversation_id: string | null;
}

export interface StoredMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  error: string | null;
  result: QueryResponse | null;
  created_at: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface Conversation extends ConversationSummary {
  messages: StoredMessage[];
}

export interface ApiError {
  detail: string;
}

export type ViewMode = "table" | "card";
