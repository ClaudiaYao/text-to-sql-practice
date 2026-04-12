from pydantic import BaseModel


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    sql: str
    columns: list[str]
    rows: list[list]
    row_count: int
    execution_ms: float


class ErrorResponse(BaseModel):
    detail: str
    sql: str | None = None
