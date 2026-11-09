"""
Golden-set evaluation runner (live: needs Postgres AND AWS Bedrock credentials).

    python -m tests.golden.runner                       # whole set
    python -m tests.golden.runner --split dev           # tune on dev …
    python -m tests.golden.runner --split heldout       # … and only report heldout occasionally
    python -m tests.golden.runner --tier complex --limit 5 --concurrency 2
    python -m tests.golden.runner --threshold 0.99      # exit code 1 below threshold

The SQL cache is disabled for the run so every question exercises generation.
A case passes when its result set equals the reference result set (see scoring.py), or — for
unanswerable/unsafe prompts — when the pipeline refuses (Unanswerable) without returning data.
"""
import argparse
import asyncio
import json
import math
import os
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

GOLDEN_DIR = Path(__file__).resolve().parent
GOLDEN_PATH = GOLDEN_DIR / "sakila_golden.json"
REPORT_DIR = GOLDEN_DIR / "reports"


@dataclass
class CaseResult:
    id: str
    tier: str
    split: str
    question: str
    passed: bool
    reason: str
    outcome: str  # result | refused | pipeline_error | llm_error | error
    generated_sql: str = ""
    reference_sql: str = ""
    attempts: int = 0
    complex: bool = False
    agreement: float | None = None
    seconds: float = 0.0
    extra_columns: int = 0
    detail: dict = field(default_factory=dict)


def load_cases(split: str | None = None, tier: str | None = None, limit: int | None = None) -> list[dict]:
    cases = json.load(open(GOLDEN_PATH, encoding="utf-8"))
    if split:
        cases = [c for c in cases if c["split"] == split]
    if tier:
        cases = [c for c in cases if c["tier"] == tier]
    return cases[:limit] if limit else cases


def wilson_lower(passed: int, total: int, z: float = 1.96) -> float:
    """Lower bound of the 95% Wilson interval — what the true accuracy is at least, statistically."""
    if total == 0:
        return 0.0
    p = passed / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return (centre - margin) / denom


async def run_case(case: dict, run_pipeline, session_factory, execute_query, compare_results, exceptions) -> CaseResult:
    Unanswerable, PipelineError, LLMError = exceptions
    base = dict(id=case["id"], tier=case["tier"], split=case["split"], question=case["question"],
                reference_sql=case["sql"] or "")
    t0 = time.perf_counter()
    async with session_factory() as session:
        try:
            result = await run_pipeline(case["question"], session, case["history"] or None)
        except Unanswerable as exc:
            ok = case["expect"] == "refusal"
            return CaseResult(**base, passed=ok, outcome="refused", seconds=time.perf_counter() - t0,
                              reason=f"refused: {exc}" if ok else f"wrongly refused: {exc}")
        except PipelineError as exc:
            return CaseResult(**base, passed=False, outcome="pipeline_error", seconds=time.perf_counter() - t0,
                              generated_sql=exc.sql or "", reason=str(exc).splitlines()[0])
        except LLMError as exc:
            return CaseResult(**base, passed=False, outcome="llm_error", seconds=time.perf_counter() - t0, reason=str(exc))
        except Exception as exc:  # noqa: BLE001
            return CaseResult(**base, passed=False, outcome="error", seconds=time.perf_counter() - t0,
                              reason=f"{type(exc).__name__}: {exc}")

        elapsed = time.perf_counter() - t0
        common = dict(generated_sql=result.sql, attempts=result.attempts, complex=result.complex,
                      agreement=result.agreement, seconds=elapsed)
        if case["expect"] == "refusal":
            return CaseResult(**base, passed=False, outcome="result", reason="answered a request that should be refused", **common)

        ref = await execute_query(session, case["sql"], 5000)
        verdict = compare_results(ref.rows, result.rows, ordered=case["ordered"])
        return CaseResult(**base, passed=verdict.correct, outcome="result", reason=verdict.reason,
                          extra_columns=verdict.extra_columns, **common)


async def evaluate(cases: list[dict], concurrency: int = 4) -> list[CaseResult]:
    from app.database import AsyncSessionLocal, execute_query
    from app.services.llm import LLMError, Unanswerable
    from app.services.pipeline import PipelineError, run_pipeline
    from tests.golden.scoring import compare_results

    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def one(case):
        nonlocal done
        async with sem:
            r = await run_case(case, run_pipeline, AsyncSessionLocal, execute_query, compare_results,
                               (Unanswerable, PipelineError, LLMError))
        done += 1
        print(f"[{done:>3}/{len(cases)}] {'PASS' if r.passed else 'FAIL'} {r.id:<9} {r.seconds:5.1f}s  {r.question[:60]}", flush=True)
        return r

    return await asyncio.gather(*(one(c) for c in cases))


def summarize(results: list[CaseResult]) -> dict:
    by_tier: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        by_tier[r.tier].append(r)
    passed = sum(r.passed for r in results)
    return {
        "total": len(results),
        "passed": passed,
        "accuracy": round(passed / len(results), 4) if results else 0.0,
        "accuracy_95ci_lower": round(wilson_lower(passed, len(results)), 4),
        "by_tier": {t: {"passed": sum(x.passed for x in rs), "total": len(rs),
                        "accuracy": round(sum(x.passed for x in rs) / len(rs), 3)} for t, rs in by_tier.items()},
        "by_split": {s: {"passed": sum(x.passed for x in rs), "total": len(rs)}
                     for s in ("dev", "heldout") if (rs := [r for r in results if r.split == s])},
        "avg_seconds": round(sum(r.seconds for r in results) / len(results), 2) if results else 0,
    }


def print_report(results: list[CaseResult], summary: dict) -> None:
    print("\n" + "=" * 72)
    print(f"{'tier':<14}{'passed':>8}{'total':>7}{'accuracy':>10}")
    for tier, s in summary["by_tier"].items():
        print(f"{tier:<14}{s['passed']:>8}{s['total']:>7}{s['accuracy']:>10.1%}")
    print("-" * 39)
    print(f"{'OVERALL':<14}{summary['passed']:>8}{summary['total']:>7}{summary['accuracy']:>10.1%}")
    print(f"95% confidence: true accuracy is at least {summary['accuracy_95ci_lower']:.1%} (n={summary['total']})")
    for split, s in summary["by_split"].items():
        print(f"  {split:<8} {s['passed']}/{s['total']}")
    fails = [r for r in results if not r.passed]
    if fails:
        print(f"\n{len(fails)} FAILURES")
        for r in fails:
            print(f"\n- {r.id} [{r.outcome}] {r.question}\n  why: {r.reason}")
            if r.generated_sql:
                print(f"  generated: {r.generated_sql[:400]}")
            if r.reference_sql:
                print(f"  reference: {r.reference_sql[:400]}")


def save_report(results: list[CaseResult], summary: dict) -> Path:
    REPORT_DIR.mkdir(exist_ok=True)
    path = REPORT_DIR / f"report-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({"summary": summary, "cases": [asdict(r) for r in results]}, indent=2, default=str))
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", choices=["dev", "heldout"])
    ap.add_argument("--tier")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--threshold", type=float, default=float(os.environ.get("GOLDEN_THRESHOLD", "0.99")))
    args = ap.parse_args()

    os.environ["CACHE_ENABLED"] = "false"  # must be set before the app settings are imported
    os.environ["CACHE_PERSIST_PATH"] = ""
    sys.path.insert(0, str(GOLDEN_DIR.parent.parent))

    cases = load_cases(args.split, args.tier, args.limit)
    if not cases:
        print("No cases selected.")
        return 2
    results = asyncio.run(evaluate(cases, args.concurrency))
    summary = summarize(results)
    print_report(results, summary)
    print(f"\nreport saved to {save_report(results, summary)}")
    return 0 if summary["accuracy"] >= args.threshold else 1


if __name__ == "__main__":
    raise SystemExit(main())
