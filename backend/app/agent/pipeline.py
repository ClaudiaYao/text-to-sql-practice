"""
Agentic query pipeline — Phase 1.

Flow per request:
  1. Fetch live DB schema
  2. Ask LLM to generate SQL                    (gemini.generate_sql)
  3. Validate SQL syntax locally                 (sql_validator.validate_sql)
  4. Execute against PostgreSQL
  5. On any failure (syntax or DB error):
       → ask LLM to correct the SQL             (gemini.correct_sql)
       → re-validate → re-execute
       → repeat up to MAX_RETRIES total attempts

The LLM's ERROR: signal (unanswerable question) short-circuits all retries immediately.
"""
import logging
import time
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.gemini import correct_sql, generate_sql
from app.agent.sql_validator import validate_sql
from app.database import execute_query, get_schema_description

logger = logging.getLogger(__name__)

MAX_RETRIES = 3  # total attempts (1 initial + 2 corrections)


@dataclass
class PipelineResult:
    sql: str
    columns: list[str]
    rows: list[list]
    row_count: int
    execution_ms: float
    attempts: int


class PipelineError(Exception):
    """Raised when all retry attempts are exhausted."""


async def run_pipeline(question: str, db: AsyncSession) -> PipelineResult:
    """
    Run the full text-to-SQL pipeline with self-correction.

    Raises:
        ValueError       — LLM signals the question cannot be answered (no retries)
        PipelineError    — all attempts exhausted
    """
    schema = await get_schema_description(db)

    sql: str | None = None
    last_error: str | None = None
    execution_ms = 0.0

    for attempt in range(1, MAX_RETRIES + 1):
        # ── Step 1: Generate or correct SQL ───────────────────────────────
        if attempt == 1:
            logger.info("[pipeline] attempt %d — generating SQL", attempt)
            sql = await generate_sql(question, schema)
            # ValueError propagates up immediately (unanswerable question)
        else:
            logger.info("[pipeline] attempt %d — correcting SQL. Last error: %s", attempt, last_error)
            sql = await correct_sql(question, schema, sql, last_error)  # type: ignore[arg-type]
            # ValueError propagates up immediately

        # ── Step 2: Validate syntax ────────────────────────────────────────
        validation_error = validate_sql(sql)
        if validation_error:
            logger.warning("[pipeline] attempt %d — validation failed: %s", attempt, validation_error)
            last_error = validation_error
            continue  # retry with correction

        # ── Step 3: Execute ────────────────────────────────────────────────
        t0 = time.perf_counter()
        try:
            columns, rows = await execute_query(db, sql)
            execution_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "[pipeline] attempt %d — success (%d rows, %.1f ms)",
                attempt, len(rows), execution_ms,
            )
            return PipelineResult(
                sql=sql,
                columns=columns,
                rows=rows,
                row_count=len(rows),
                execution_ms=round(execution_ms, 2),
                attempts=attempt,
            )
        except Exception as exc:
            execution_ms = (time.perf_counter() - t0) * 1000
            last_error = str(exc)
            logger.warning("[pipeline] attempt %d — execution failed: %s", attempt, last_error)
            # continue to next attempt

    raise PipelineError(
        f"Query failed after {MAX_RETRIES} attempts. "
        f"Last error: {last_error}\n\nLast generated SQL:\n{sql}"
    )
