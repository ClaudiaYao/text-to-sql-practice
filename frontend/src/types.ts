export interface QueryResponse {
  sql: string;
  columns: string[];
  rows: unknown[][];
  row_count: number;
  execution_ms: number;
}

export interface ApiError {
  detail: string;
}

export type ViewMode = "table" | "card";
