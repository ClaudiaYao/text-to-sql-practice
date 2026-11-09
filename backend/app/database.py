"""Async SQLAlchemy engine + safe read-only query execution."""
import datetime as dt
import decimal
import time
import uuid
from dataclasses import dataclass
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.constants import BLOCKED_COLUMNS

# Defence in depth: every connection is read-only and has a server-side timeout, regardless of
# what the SQL validator lets through.
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    connect_args={
        "server_settings": {
            "default_transaction_read_only": "on",
            "statement_timeout": str(settings.query_timeout_ms),
            "application_name": "text-to-sql",
        }
    },
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]
    truncated: bool
    execution_ms: float


def _jsonable(value):
    """Convert driver types into plain JSON-friendly values (also used for stable result signatures)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, decimal.Decimal):
        return float(value) if value.is_finite() else str(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(value))} bytes>"
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


async def execute_query(session: AsyncSession, sql: str, max_rows: int | None = None) -> QueryResult:
    """
    Run one validated SELECT and return at most `max_rows` rows.

    The session is rolled back before and after, so a failed attempt can never leave the
    connection in an aborted-transaction state for the next retry. The raw driver API is used
    (not text()) so characters like ':' in string literals are never mistaken for bind params.
    """
    limit = max_rows if max_rows is not None else settings.max_rows
    await session.rollback()
    t0 = time.perf_counter()
    try:
        conn = await session.connection()
        result = await conn.exec_driver_sql(sql)
        columns = list(result.keys())
        fetched = result.fetchmany(limit + 1)
    finally:
        await session.rollback()
    elapsed = (time.perf_counter() - t0) * 1000

    truncated = len(fetched) > limit
    keep = [i for i, c in enumerate(columns) if c.lower() not in BLOCKED_COLUMNS]
    rows = [[_jsonable(row[i]) for i in keep] for row in fetched[:limit]]
    return QueryResult(
        columns=[columns[i] for i in keep],
        rows=rows,
        truncated=truncated,
        execution_ms=round(elapsed, 2),
    )
