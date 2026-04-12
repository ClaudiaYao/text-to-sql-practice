from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_schema_description(session: AsyncSession) -> str:
    """Return a compact DDL-style description of all user tables and their columns."""
    tables_query = text(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type IN ('BASE TABLE', 'VIEW')
        ORDER BY table_type DESC, table_name
        """
    )
    result = await session.execute(tables_query)
    tables = [row[0] for row in result.fetchall()]

    schema_parts: list[str] = []
    for table in tables:
        cols_query = text(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :table
            ORDER BY ordinal_position
            """
        )
        cols_result = await session.execute(cols_query, {"table": table})
        cols = cols_result.fetchall()
        col_defs = ", ".join(
            f"{col[0]} {col[1].upper()}{'' if col[2] == 'NO' else ' NULL'}"
            for col in cols
        )
        schema_parts.append(f"{table}({col_defs})")

    return "\n".join(schema_parts)


async def execute_query(session: AsyncSession, sql: str) -> tuple[list[str], list[list]]:
    """Execute a SELECT query and return (columns, rows)."""
    result = await session.execute(text(sql))
    columns = list(result.keys())
    rows = [list(row) for row in result.fetchall()]
    return columns, rows
