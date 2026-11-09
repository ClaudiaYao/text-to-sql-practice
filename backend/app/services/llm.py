"""LLM access (AWS Bedrock Converse API) and the five LLM tasks the pipeline needs."""
import asyncio
import logging
import re
from dataclasses import dataclass

from app.config import settings
from app.services import prompts
from app.services.aws import bedrock_client
from app.services.domain_notes import SAKILA_NOTES

logger = logging.getLogger(__name__)


class Unanswerable(ValueError):
    """The model decided the question cannot (or must not) be answered with this schema."""


class LLMError(RuntimeError):
    """Bedrock call failed."""


@dataclass
class Candidate:
    sql: str
    plan: str = ""


# ── Bedrock ───────────────────────────────────────────────────────────────────

async def _converse(system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 1200) -> str:
    def _invoke() -> str:
        response = bedrock_client().converse(
            modelId=settings.bedrock_model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"temperature": temperature, "maxTokens": max_tokens},
        )
        parts = response["output"]["message"]["content"]
        return "".join(p.get("text", "") for p in parts).strip()

    try:
        return await asyncio.get_running_loop().run_in_executor(None, _invoke)
    except Exception as exc:  # botocore errors: throttling, access denied, validation…
        raise LLMError(f"Bedrock call failed: {exc}") from exc


# ── Parsing ───────────────────────────────────────────────────────────────────

_SQL_TAG = re.compile(r"<sql>(.*?)(?:</sql>|$)", re.DOTALL | re.IGNORECASE)
_PLAN_TAG = re.compile(r"<plan>(.*?)</plan>", re.DOTALL | re.IGNORECASE)


def parse_response(raw: str) -> Candidate:
    """Extract SQL (and plan) from a model reply. Raises Unanswerable on an ERROR: reply."""
    text = raw.strip()
    plan_match = _PLAN_TAG.search(text)
    plan = plan_match.group(1).strip() if plan_match else ""

    sql_match = _SQL_TAG.search(text)
    if sql_match:
        sql = sql_match.group(1)
    else:
        sql = _PLAN_TAG.sub("", text)
    sql = re.sub(r"^\s*```(?:sql)?\s*", "", sql.strip(), flags=re.IGNORECASE)
    sql = re.sub(r"\s*```\s*$", "", sql).strip().rstrip(";").strip()

    error = re.search(r"(?im)^\s*ERROR:\s*(.+)$", sql) or re.search(r"(?im)^\s*ERROR:\s*(.+)$", text)
    if error and not re.match(r"(?is)\s*(select|with|\()", sql):
        raise Unanswerable(error.group(1).strip())
    return Candidate(sql=sql, plan=plan)


# ── Tasks ─────────────────────────────────────────────────────────────────────

async def generate_candidates(
    question: str, schema: str, examples: list[dict], *, reasoning: bool, n: int
) -> list[Candidate]:
    """
    Generate up to n SQL candidates. The first is greedy (temperature 0); extra ones are sampled for
    diversity so the pipeline can vote on their *results*. Raises Unanswerable if the greedy answer
    says so; failures of the extra samples are ignored.
    """
    system = prompts.generation_system(schema, SAKILA_NOTES, examples, reasoning)
    max_tokens = 1500 if reasoning else 900
    calls = [_converse(system, question, temperature=0.0, max_tokens=max_tokens)]
    calls += [
        _converse(system, question, temperature=settings.candidate_temperature, max_tokens=max_tokens)
        for _ in range(max(0, n - 1))
    ]
    results = await asyncio.gather(*calls, return_exceptions=True)

    first = results[0]
    if isinstance(first, BaseException):
        raise first
    candidates = [parse_response(first)]  # may raise Unanswerable
    for r in results[1:]:
        if isinstance(r, BaseException):
            logger.warning("[llm] extra candidate failed: %s", r)
            continue
        try:
            candidates.append(parse_response(r))
        except Unanswerable:
            continue
    return candidates


async def correct_sql(
    question: str, schema: str, examples: list[dict], failed_sql: str, problem: str,
    previous: list[str], *, reasoning: bool,
) -> Candidate:
    system = prompts.correction_system(schema, SAKILA_NOTES, examples, reasoning)
    user = prompts.correction_user(question, failed_sql, problem, previous)
    raw = await _converse(system, user, temperature=0.0, max_tokens=1500 if reasoning else 900)
    return parse_response(raw)


async def rewrite_question(question: str, history: list[dict]) -> str:
    raw = await _converse(prompts.REWRITE_SYSTEM, prompts.rewrite_user(question, history), max_tokens=300)
    return raw.strip().strip('"') or question


async def judge_empty(question: str, sql: str, schema: str) -> str | None:
    """None if an empty result looks right, else a hint describing what to fix."""
    raw = await _converse(
        prompts.judge_empty_system(schema, SAKILA_NOTES), prompts.judge_empty_user(question, sql), max_tokens=200
    )
    if raw.upper().startswith("RETRY"):
        return raw.split(":", 1)[1].strip() if ":" in raw else "The empty result looks wrong."
    return None


async def summarize(question: str, columns: list[str], rows: list[list], row_count: int, truncated: bool) -> str:
    shown = rows[:40]
    return await _converse(
        prompts.ANSWER_SYSTEM,
        prompts.answer_user(question, columns, shown, row_count, truncated),
        max_tokens=400,
    )
