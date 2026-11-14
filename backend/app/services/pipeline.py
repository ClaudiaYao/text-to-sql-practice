"""
Question → SQL → data → answer, tuned for accuracy and cost.

    question (+ chat history)
      │  follow-up? → LLM rewrites it into a standalone question
      ▼
    SQL cache hit?  ──yes──► validate → execute (fresh data) ─────────────┐
      │ no                                                                 │
      ▼                                                                    │
    pick few-shot examples (keyword + technique match)                     │
    simple question  → 1 greedy candidate                                  │
    complex question → plan-then-SQL, N candidates (1 greedy + N-1 sampled)│
      ▼                                                                    │
    validate (sqlglot) → execute each candidate (read-only, timeout)       │
      ▼                                                                    │
    no candidate ran?  → self-correct with the DB error (≤ MAX_ATTEMPTS)   │
    some ran?          → majority vote on RESULT SETS (self-consistency)   │
    0 rows?            → LLM judge; if the filter looks wrong → correct    │
      ▼                                                                    │
    cache the SQL  ◄───────────────────────────────────────────────────────┘
      ▼
    natural-language answer (answer cache keyed on the actual result)
"""
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import QueryResult, execute_query
from app.services import llm
from app.services.cache import answer_cache, make_key, normalize_question, sql_cache
from app.services.examples import select_examples
from app.services.llm import Candidate, Unanswerable
from app.services.schema import get_schema_context
from app.services.sql_validator import validate_sql

logger = logging.getLogger(__name__)

# Questions needing ranking, windowing, set logic, subqueries or date arithmetic get the expensive
# treatment (plan-then-SQL + several candidates voted on by result). Deliberately liberal: a false
# positive costs a few extra tokens, a false negative costs accuracy.
_STRONG = re.compile(
    r"\b(rank\w*|compar\w*|versus|vs|trend|over time|month over month|year over year|percent\w*|share|"
    r"ratio|proportion|running|cumulative|consecutive|previous|difference|growth|both|never|without|"
    r"except|but not|not in|at least|at most|than the average|than average|above average|below average|"
    r"median|percentile|quartile|nth|second highest|third highest)\b",
    re.IGNORECASE,
)
_WEAK = re.compile(
    r"\b(top \d+|per|each|every|more than|fewer than|less than|most|least|highest|lowest|longest|"
    r"shortest|first|last|between|since|during|distinct|unique|above|below|average)\b",
    re.IGNORECASE,
)


def is_complex(question: str) -> bool:
    return bool(
        _STRONG.search(question)
        or len(_WEAK.findall(question)) >= 2
        or len(question.split()) >= 18
    )


@dataclass
class PipelineResult:
    sql: str
    columns: list[str]
    rows: list[list]
    row_count: int
    truncated: bool
    execution_ms: float
    attempts: int  # LLM generation/correction rounds (0 = served entirely from the SQL cache)
    answer: str
    standalone_question: str
    cached: bool = False  # SQL came from the cache
    complex: bool = False
    candidates: int = 1
    agreement: float | None = None  # share of candidates whose results matched the winner (complex only)
    plan: str = ""


class PipelineError(Exception):
    """All attempts failed to produce a runnable query."""

    def __init__(self, message: str, sql: str | None = None):
        super().__init__(message)
        self.sql = sql


@dataclass
class _Outcome:
    candidate: Candidate
    result: QueryResult | None = None
    error: str | None = None
    signature: tuple = field(default_factory=tuple)


# ── helpers ───────────────────────────────────────────────────────────────────

def result_signature(columns: list[str], rows: list[list]) -> tuple:
    """Order-insensitive, column-name-insensitive fingerprint of a result set."""
    def norm(v):
        if isinstance(v, float):
            return round(v, 4)
        return v

    return (len(columns), tuple(sorted(repr([norm(v) for v in r]) for r in rows)))


def vote(outcomes: list[_Outcome]) -> _Outcome:
    """Pick the outcome whose result set most candidates agree on; ties go to the earliest (greedy) one."""
    groups: dict[tuple, list[_Outcome]] = defaultdict(list)
    for o in outcomes:
        groups[o.signature].append(o)
    # Prefer non-empty result groups over empty ones, then the biggest group, then the earliest member.
    order = {id(o): i for i, o in enumerate(outcomes)}
    best = max(
        groups.values(),
        key=lambda g: (bool(g[0].result and g[0].result.rows), len(g), -min(order[id(o)] for o in g)),
    )
    return best[0]


async def _try(db: AsyncSession, candidate: Candidate) -> _Outcome:
    error = validate_sql(candidate.sql)
    if error:
        logger.warning("[pipeline] validation failed: %s | %s", error, candidate.sql)
        return _Outcome(candidate, error=error)
    try:
        result = await execute_query(db, candidate.sql)
    except Exception as exc:
        message = str(getattr(exc, "orig", exc)).strip() or type(exc).__name__
        logger.warning("[pipeline] execution failed: %s | %s", message, candidate.sql)
        return _Outcome(candidate, error=message)
    return _Outcome(candidate, result=result, signature=result_signature(result.columns, result.rows))


async def _answer(question: str, result: QueryResult) -> str:
    row_count = len(result.rows)
    # Keyed on exactly what the summariser would see, so a changed result regenerates the answer.
    key = make_key("answer", normalize_question(question), repr(result.columns), repr(result.rows[:40]),
                   str(len(result.rows)), str(result.truncated))
    if settings.cache_enabled:
        hit = answer_cache.get(key)
        if hit:
            return hit
    try:
        text = await llm.summarize(question, result.columns, result.rows, row_count, result.truncated)
    except Exception:
        logger.exception("[pipeline] answer generation failed — using fallback text")
        return f"The query returned {row_count} row{'s' if row_count != 1 else ''}."
    if settings.cache_enabled and text:
        answer_cache.set(key, text)
    return text


def _finish(sql: str, result: QueryResult, answer: str, standalone: str, **extra) -> PipelineResult:
    return PipelineResult(
        sql=sql,
        columns=result.columns,
        rows=result.rows,
        row_count=len(result.rows),
        truncated=result.truncated,
        execution_ms=result.execution_ms,
        answer=answer,
        standalone_question=standalone,
        **extra,
    )


# ── main entry point ──────────────────────────────────────────────────────────

async def run_pipeline(
    question: str, db: AsyncSession, history: list[dict] | None = None
) -> PipelineResult:
    """
    Raises:
        Unanswerable  — the model says the question cannot / must not be answered (no retries)
        PipelineError — no runnable query after MAX_ATTEMPTS
    """
    standalone = question
    if history:
        try:
            standalone = await llm.rewrite_question(question, history)
        except Exception:
            logger.exception("[pipeline] follow-up rewrite failed — using the message as is")
    standalone = standalone.strip()

    schema = await get_schema_context(db)
    cache_key = make_key("sql", schema.hash, normalize_question(standalone))

    # SQL cache — skip the LLM, still hit the DB so data is fresh
    if settings.cache_enabled:
        cached_sql = sql_cache.get(cache_key)
        if cached_sql:
            outcome = await _try(db, Candidate(cached_sql))
            if outcome.result is not None:
                logger.info("[pipeline] SQL cache hit")
                answer = await _answer(standalone, outcome.result)
                return _finish(cached_sql, outcome.result, answer, standalone, attempts=0, cached=True)
            logger.warning("[pipeline] cached SQL failed (%s) — evicting", outcome.error)
            sql_cache.delete(cache_key)

    # Generate
    complex_q = is_complex(standalone)
    examples = select_examples(standalone, settings.fewshot_top_k + (2 if complex_q else 0))
    n = max(1, settings.complex_candidates) if complex_q else 1
    logger.info("[pipeline] complex=%s candidates=%d examples=%d", complex_q, n, len(examples))

    candidates = await llm.generate_candidates(standalone, schema.text, examples, reasoning=complex_q, n=n)
    attempts = 1
    

    outcomes: list[_Outcome] = []
    seen: set[str] = set()
    for cand in candidates:
        key = re.sub(r"\s+", " ", cand.sql.lower())
        if key in seen:
            # identical SQL: counts as an agreeing vote without re-running
            if outcomes:
                twin = next((o for o in outcomes if re.sub(r"\s+", " ", o.candidate.sql.lower()) == key), None)
                if twin is not None and twin.result is not None:
                    outcomes.append(_Outcome(cand, twin.result, None, twin.signature))
            continue
        seen.add(key)
        outcomes.append(await _try(db, cand))

    good = [o for o in outcomes if o.result is not None]
    tried = [o.candidate.sql for o in outcomes]
    last = outcomes[0]

    # Self-correct if nothing ran
    while not good and attempts < settings.max_attempts:
        attempts += 1
        fixed = await llm.correct_sql(
            standalone, schema.text, examples, last.candidate.sql, last.error or "Unknown error",
            [t for t in tried if t != last.candidate.sql], reasoning=complex_q,
        )
        outcome = await _try(db, fixed)
        tried.append(fixed.sql)
        last = outcome
        if outcome.result is not None:
            good = [outcome]

    if not good:
        raise PipelineError(
            f"Could not produce a working query after {attempts} attempts. Last error: {last.error}",
            sql=last.candidate.sql,
        )

    # Majority vote on results
    chosen = vote(good)
    agreement = (
        round(sum(1 for o in good if o.signature == chosen.signature) / len(outcomes), 2) if n > 1 else None
    )

    # Empty result sanity check (LLM-judged, replaces keyword heuristics)
    if not chosen.result.rows and attempts < settings.max_attempts:
        try:
            hint = await llm.judge_empty(standalone, chosen.candidate.sql, schema.text)
        except Exception:
            hint = None
        if hint:
            attempts += 1
            logger.info("[pipeline] empty result judged suspicious: %s", hint)
            try:
                fixed = await llm.correct_sql(
                    standalone, schema.text, examples, chosen.candidate.sql,
                    f"The query returned 0 rows, which looks wrong. {hint}", tried, reasoning=complex_q,
                )
                retry = await _try(db, fixed)
                if retry.result is not None and retry.result.rows:
                    chosen = retry
            except Unanswerable:
                pass

    # Cache + answer
    result = chosen.result
    if settings.cache_enabled and result.rows:
        sql_cache.set(cache_key, chosen.candidate.sql)
    answer = await _answer(standalone, result)
    return _finish(
        chosen.candidate.sql, result, answer, standalone,
        attempts=attempts, complex=complex_q, candidates=len(candidates),
        agreement=agreement, plan=chosen.candidate.plan,
    )
