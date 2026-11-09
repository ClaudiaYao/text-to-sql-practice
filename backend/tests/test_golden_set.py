"""
Golden-set integrity (no DB), reference validation + offline oracle run (needs Postgres, auto-skips).

The oracle run swaps the LLM for a fake that returns the reference SQL, then pushes every case through
the REAL pipeline, validator, executor and scorer. It must score 100% — proving the plumbing — and the
mutation test proves the scorer rejects wrong answers. The live-model score is `tests/golden/runner.py`.
"""
import json
import re
from collections import Counter

import pytest

from app.config import BACKEND_DIR, settings
from app.services.cache import normalize_question
from app.services.llm import Candidate, Unanswerable
from app.services.sql_validator import validate_sql
from tests.golden.runner import GOLDEN_PATH, load_cases, run_case, summarize, wilson_lower
from tests.golden.scoring import compare_results

CASES = json.load(open(GOLDEN_PATH, encoding="utf-8"))
ANSWERABLE = [c for c in CASES if c["expect"] == "result"]
REFUSALS = [c for c in CASES if c["expect"] == "refusal"]


# ── structure (no database) ──────────────────────────────────────────────────

def test_size_and_tier_coverage():
    assert len(CASES) >= 100
    tiers = Counter(c["tier"] for c in CASES)
    assert set(tiers) == {"simple", "joins", "aggregation", "complex", "dates", "edge", "followup", "unanswerable", "unsafe"}
    assert tiers["complex"] >= 15 and tiers["followup"] >= 5 and tiers["unsafe"] + tiers["unanswerable"] >= 10


def test_ids_unique_and_fields_present():
    assert len({c["id"] for c in CASES}) == len(CASES)
    for c in CASES:
        assert c["split"] in ("dev", "heldout") and c["expect"] in ("result", "refusal")
        assert c["question"].strip()


def test_answerable_cases_have_valid_read_only_reference_sql():
    for c in ANSWERABLE:
        assert c["sql"], c["id"]
        assert validate_sql(c["sql"]) is None, (c["id"], validate_sql(c["sql"]))


def test_refusal_cases_have_no_sql():
    assert all(c["sql"] is None for c in REFUSALS)


def test_followups_have_history_and_others_do_not():
    for c in CASES:
        assert bool(c["history"]) == (c["tier"] == "followup"), c["id"]
        for m in c["history"]:
            assert m["role"] in ("user", "assistant") and m["content"]


def test_heldout_split_is_about_a_third_in_every_tier():
    for tier in {c["tier"] for c in CASES}:
        rows = [c for c in CASES if c["tier"] == tier]
        held = sum(c["split"] == "heldout" for c in rows)
        assert 1 <= held <= len(rows) // 2 + 1, tier


def _tokens(q):
    return set(re.findall(r"[a-z0-9']+", normalize_question(q))) - {"the", "a", "of", "in", "is", "are", "what", "which", "how", "many"}


def test_no_leakage_between_golden_questions_and_few_shot_examples():
    """A golden question that is (nearly) a few-shot example would measure memorisation, not skill."""
    seeds = json.load(open(BACKEND_DIR / "data" / "seed" / "sakila_examples.json"))
    for c in CASES:
        for ex in seeds:
            a, b = _tokens(c["question"]), _tokens(ex["question"])
            jaccard = len(a & b) / max(1, len(a | b))
            assert normalize_question(c["question"]) != normalize_question(ex["question"]), (c["id"], ex["question"])
            assert jaccard < 0.7, (c["id"], c["question"], ex["question"], round(jaccard, 2))


def test_wilson_interval_sanity():
    assert wilson_lower(100, 100) == pytest.approx(0.963, abs=0.002)
    assert wilson_lower(99, 100) < 0.99
    assert wilson_lower(0, 0) == 0.0


def test_load_cases_filters():
    assert all(c["split"] == "heldout" for c in load_cases(split="heldout"))
    assert len(load_cases(tier="complex", limit=3)) == 3


# ── reference SQL against the real database ──────────────────────────────────

async def test_every_reference_query_runs_and_has_the_expected_emptiness(db_session_factory):
    from app.database import execute_query

    async with db_session_factory() as s:
        for c in ANSWERABLE:
            res = await execute_query(s, c["sql"], 5000)
            assert len(res.rows) <= settings.max_rows, f"{c['id']} reference has {len(res.rows)} rows, above MAX_ROWS"
            assert (len(res.rows) == 0) == c["expect_empty"], (c["id"], len(res.rows))


# ── offline oracle: real pipeline + DB + scorer, fake LLM that returns the reference SQL ──

@pytest.fixture
def oracle(monkeypatch):
    from app.services import llm, pipeline

    current: dict = {}

    async def generate(question, schema, examples, *, reasoning, n):
        if current["case"]["expect"] == "refusal":
            raise Unanswerable("refused (oracle)")
        return [Candidate(current["case"]["sql"])]

    async def summarize(*a, **k):
        return "oracle answer"

    async def rewrite(question, history):
        return question

    async def judge(*a, **k):
        return None

    monkeypatch.setattr(settings, "cache_enabled", False)
    monkeypatch.setattr(llm, "generate_candidates", generate)
    monkeypatch.setattr(llm, "summarize", summarize)
    monkeypatch.setattr(llm, "rewrite_question", rewrite)
    monkeypatch.setattr(llm, "judge_empty", judge)
    return current


async def test_oracle_scores_100_percent_through_the_real_pipeline(db_session_factory, oracle):
    from app.database import execute_query
    from app.services.llm import LLMError
    from app.services.pipeline import PipelineError, run_pipeline

    results = []
    for case in CASES:
        oracle["case"] = case
        results.append(await run_case(case, run_pipeline, db_session_factory, execute_query, compare_results,
                                      (Unanswerable, PipelineError, LLMError)))
    failures = [(r.id, r.reason) for r in results if not r.passed]
    assert not failures, failures
    summary = summarize(results)
    assert summary["accuracy"] == 1.0 and summary["total"] == len(CASES)


async def test_scorer_rejects_mutated_wrong_answers_and_accepts_extra_columns(db_session_factory):
    from app.database import execute_query

    async with db_session_factory() as s:
        for c in ANSWERABLE:
            ref = await execute_query(s, c["sql"], 5000)
            if not ref.rows:
                continue
            wrong_sql = (
                f"SELECT * FROM ({c['sql']}) t LIMIT 1" if len(ref.rows) > 1 else "SELECT 123456789 AS x"
            )
            wrong = await execute_query(s, wrong_sql, 5000)
            assert not compare_results(ref.rows, wrong.rows, ordered=c["ordered"]).correct, c["id"]

            wide = await execute_query(s, f"SELECT 1 AS extra, t.* FROM ({c['sql']}) t", 5000)
            verdict = compare_results(ref.rows, wide.rows, ordered=c["ordered"])
            assert verdict.correct and verdict.extra_columns == 1, (c["id"], verdict)
