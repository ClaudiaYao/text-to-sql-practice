import pytest

from tests.golden import runner
from tests.golden.runner import CaseResult, run_case_with_retries


def _res(outcome, passed=False):
    return CaseResult(id="x", tier="t", split="dev", question="q", passed=passed, reason="", outcome=outcome)


def _seq(*outcomes):
    calls = []
    outs = iter(outcomes)

    async def once():
        calls.append(1)
        o = next(outs)
        return _res(o, passed=(o == "ok"))

    return once, calls


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def nosleep(_):
        return None

    monkeypatch.setattr(runner.asyncio, "sleep", nosleep)


async def test_error_outcome_is_rerun_until_it_answers():
    once, calls = _seq("llm_error", "pipeline_error", "ok")
    r = await run_case_with_retries(once, retries=2)
    assert len(calls) == 3 and r.retries == 2 and r.outcome == "ok"


async def test_retries_are_capped():
    once, calls = _seq("error", "error", "error", "error")
    r = await run_case_with_retries(once, retries=2)
    assert len(calls) == 3 and r.retries == 2 and not r.passed


@pytest.mark.parametrize("outcome", ["result", "refused"])
async def test_wrong_answers_and_refusals_are_never_rerun(outcome):
    once, calls = _seq(outcome, "ok")
    r = await run_case_with_retries(once, retries=5)
    assert len(calls) == 1 and r.retries == 0 and r.outcome == outcome


async def test_retries_zero_disables_reruns():
    once, calls = _seq("llm_error", "ok")
    assert (await run_case_with_retries(once, retries=0)).outcome == "llm_error" and len(calls) == 1
