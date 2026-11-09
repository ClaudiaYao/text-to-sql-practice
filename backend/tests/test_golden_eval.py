"""
Live accuracy evaluation: real Bedrock model + real Postgres. Not part of the default run.

    pytest -m eval -s                         # whole golden set
    GOLDEN_THRESHOLD=0.95 pytest -m eval -s   # custom bar (default 0.99)

Prefer the CLI for day-to-day work (`python -m tests.golden.runner --help`): it has split/tier filters.
"""
import os

import pytest

from app.config import settings
from tests.golden.runner import evaluate, load_cases, print_report, save_report, summarize

pytestmark = pytest.mark.eval


async def test_golden_set_accuracy(db_session_factory, monkeypatch):
    monkeypatch.setattr(settings, "cache_enabled", False)
    results = await evaluate(load_cases(), concurrency=int(os.environ.get("GOLDEN_CONCURRENCY", "4")))
    summary = summarize(results)
    print_report(results, summary)
    save_report(results, summary)
    threshold = float(os.environ.get("GOLDEN_THRESHOLD", "0.99"))
    assert summary["accuracy"] >= threshold, f"accuracy {summary['accuracy']:.1%} < {threshold:.0%}"
