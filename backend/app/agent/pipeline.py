"""
Agentic query pipeline — Phase 2.

Flow per request:
  1. Retrieve RAG context (relevant schema chunks + few-shot examples)
     → falls back to full schema if RAG is unavailable
  2. Ask LLM to generate SQL using RAG-enhanced prompt  (gemini.generate_sql)
  3. Validate SQL syntax locally                         (sql_validator.validate_sql)
  4. Execute against PostgreSQL
  5. On any failure (syntax or DB error):
       → ask LLM to correct the SQL                     (gemini.correct_sql)
       → re-validate → re-execute
       → repeat up to MAX_RETRIES total attempts

The LLM's ERROR: signal (unanswerable question) short-circuits all retries immediately.
"""
import logging
import time
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.gemini import correct_sql, generate_sql
from app.agent.rag_context import get_rag_context
from app.agent.sql_validator import validate_sql
from app.database import execute_query

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
    fewshot_used: int = field(default=0)  # number of few-shot examples injected


class PipelineError(Exception):
    """Raised when all retry attempts are exhausted."""


async def run_pipeline(question: str, db: AsyncSession) -> PipelineResult:
    """
    Run the full text-to-SQL pipeline with RAG context and self-correction.

    Raises:
        ValueError    — LLM signals the question cannot be answered (no retries)
        PipelineError — all attempts exhausted
    """
    # ── Step 1: Retrieve RAG context ──────────────────────────────────────────
    schema, fewshot_examples = await get_rag_context(question, db)
    logger.info(
        "[pipeline] RAG context: schema_lines=%d, fewshot_examples=%d",
        len(schema.splitlines()),
        len(fewshot_examples),
    )

    sql: str | None = None
    last_error: str | None = None
    execution_ms = 0.0

    for attempt in range(1, MAX_RETRIES + 1):
        # ── Step 2: Generate or correct SQL ───────────────────────────────────
        if attempt == 1:
            logger.info("[pipeline] attempt %d — generating SQL", attempt)
            sql = await generate_sql(question, schema, fewshot_examples)
        else:
            logger.info(
                "[pipeline] attempt %d — correcting SQL. Last error: %s",
                attempt, last_error,
            )
            # Correction uses same schema context but no few-shot (targeted fix)
            sql = await correct_sql(question, schema, sql, last_error)  # type: ignore[arg-type]

        # ── Step 3: Validate syntax ────────────────────────────────────────────
        validation_error = validate_sql(sql)
        if validation_error:
            logger.warning(
                "[pipeline] attempt %d — validation failed: %s", attempt, validation_error
            )
            last_error = validation_error
            continue

        # ── Step 4: Execute ────────────────────────────────────────────────────
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
                fewshot_used=len(fewshot_examples),
            )
        except Exception as exc:
            execution_ms = (time.perf_counter() - t0) * 1000
            last_error = str(exc)
            logger.warning(
                "[pipeline] attempt %d — execution failed: %s", attempt, last_error
            )

    raise PipelineError(
        f"Query failed after {MAX_RETRIES} attempts. "
        f"Last error: {last_error}\n\nLast generated SQL:\n{sql}"
    )
