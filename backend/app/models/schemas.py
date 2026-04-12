from pydantic import BaseModel


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    sql: str
    columns: list[str]
    rows: list[list]
    row_count: int
    execution_ms: float
    attempts: int  # number of LLM calls needed (1 = first try succeeded, >1 = self-corrected)


class ErrorResponse(BaseModel):
    detail: str
    sql: str | None = None
