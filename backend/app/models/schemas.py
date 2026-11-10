from typing import Literal

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None  # continue a stored conversation (server loads its history)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)


class QueryResponse(BaseModel):
    answer: str  # natural-language answer
    sql: str
    columns: list[str]
    rows: list[list]
    row_count: int
    truncated: bool  # more rows existed than MAX_ROWS
    execution_ms: float
    attempts: int  # LLM rounds used (0 = SQL cache hit, 1 = first try, >1 = self-corrected)
    cached: bool  # SQL served from cache (data still fresh)
    complex: bool  # complex-question path was used (plan + multi-candidate voting)
    candidates: int
    agreement: float | None = None  # fraction of candidates whose results matched (complex only)
    standalone_question: str  # the question after resolving chat context
    conversation_id: str | None = None  # set by /api/chat


class StoredMessage(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str  # the question, or the natural-language answer
    error: str | None = None  # set when the turn failed
    result: QueryResponse | None = None  # the stored SQL + rows of an assistant turn
    created_at: str


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class Conversation(ConversationSummary):
    messages: list[StoredMessage]
