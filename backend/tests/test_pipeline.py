"""Pipeline behaviour with a scripted LLM and a fake database — no Bedrock, no Postgres."""
import pytest

from app.database import QueryResult
from app.services import cache, pipeline
from app.services.llm import Candidate, Unanswerable
from app.services.pipeline import PipelineError, is_complex, result_signature, run_pipeline
from app.services.schema import SchemaContext


def qr(rows, cols=("a",)):
    return QueryResult(columns=list(cols), rows=rows, truncated=False, execution_ms=1.0)


class FakeEnv:
    """Scripted LLM + DB. `db` maps SQL text -> QueryResult or Exception."""

    def __init__(self, db, candidates=None, corrections=None, judge=None):
        self.db = db
        self.candidates = candidates or []
        self.corrections = list(corrections or [])
        self.judge = judge
        self.executed = []
        self.llm_calls = {"generate": 0, "correct": 0, "judge": 0, "summarize": 0, "rewrite": 0}

    async def execute(self, session, sql, max_rows=None):
        self.executed.append(sql)
        out = self.db[sql]
        if isinstance(out, Exception):
            raise out
        return out

    async def generate(self, question, schema, examples, *, reasoning, n):
        self.llm_calls["generate"] += 1
        self.last_reasoning, self.last_n = reasoning, n
        if isinstance(self.candidates, Exception):
            raise self.candidates
        return [Candidate(s) for s in self.candidates]

    async def correct(self, question, schema, examples, failed_sql, problem, previous, *, reasoning):
        self.llm_calls["correct"] += 1
        self.last_problem = problem
        nxt = self.corrections.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return Candidate(nxt)

    async def judge_empty(self, question, sql, schema):
        self.llm_calls["judge"] += 1
        return self.judge

    async def summarize(self, question, columns, rows, row_count, truncated):
        self.llm_calls["summarize"] += 1
        return f"{row_count} rows"

    async def rewrite(self, question, history):
        self.llm_calls["rewrite"] += 1
        return "standalone: " + question


@pytest.fixture
def install(monkeypatch):
    async def fake_schema(db, force=False):
        return SchemaContext("film(film_id PK)", "h1")

    def fake_validate(sql):  # the real validator has its own tests; here only DML is "invalid"
        return "Only SELECT queries are allowed; got DELETE." if sql.upper().startswith("DELETE") else None

    def _install(env: FakeEnv):
        monkeypatch.setattr(pipeline, "validate_sql", fake_validate)
        monkeypatch.setattr(pipeline, "execute_query", env.execute)
        monkeypatch.setattr(pipeline, "get_schema_context", fake_schema)
        monkeypatch.setattr(pipeline.llm, "generate_candidates", env.generate)
        monkeypatch.setattr(pipeline.llm, "correct_sql", env.correct)
        monkeypatch.setattr(pipeline.llm, "judge_empty", env.judge_empty)
        monkeypatch.setattr(pipeline.llm, "summarize", env.summarize)
        monkeypatch.setattr(pipeline.llm, "rewrite_question", env.rewrite)
        cache.clear_caches()
        return env

    yield _install
    cache.clear_caches()


async def test_first_try_success(install):
    env = install(FakeEnv({"SELECT 1": qr([[1]])}, candidates=["SELECT 1"]))
    r = await run_pipeline("how many films", object())
    assert (r.sql, r.attempts, r.cached, r.complex) == ("SELECT 1", 1, False, False)
    assert r.answer == "1 rows" and env.last_n == 1 and env.last_reasoning is False


async def test_self_correction_after_db_error(install):
    env = install(FakeEnv(
        {"SELECT bad": Exception('column "bad" does not exist'), "SELECT good": qr([[2]])},
        candidates=["SELECT bad"], corrections=["SELECT good"],
    ))
    r = await run_pipeline("q", object())
    assert r.sql == "SELECT good" and r.attempts == 2
    assert "does not exist" in env.last_problem


async def test_validation_error_triggers_correction_without_hitting_db(install):
    env = install(FakeEnv({"SELECT 1": qr([[1]])}, candidates=["DELETE FROM film"], corrections=["SELECT 1"]))
    r = await run_pipeline("q", object())
    assert r.attempts == 2 and env.executed == ["SELECT 1"]
    assert "Only SELECT" in env.last_problem


async def test_gives_up_after_max_attempts(install):
    err = Exception("boom")
    install(FakeEnv({"S1": err, "S2": err, "S3": err}, candidates=["S1"], corrections=["S2", "S3"]))
    with pytest.raises(PipelineError) as exc:
        await run_pipeline("q", object())
    assert "boom" in str(exc.value) and exc.value.sql == "S3"


async def test_unanswerable_short_circuits(install):
    env = install(FakeEnv({}, candidates=Unanswerable("not in schema")))
    with pytest.raises(Unanswerable):
        await run_pipeline("what is the weather", object())
    assert env.llm_calls["correct"] == 0


async def test_complex_question_votes_on_results(install):
    q = "for each category which film has the most rentals compared to the average"
    assert is_complex(q)
    env = install(FakeEnv(
        {"A": qr([[1], [2]]), "B": qr([[9]]), "C": qr([[2], [1]])},  # A and C agree (order-insensitive)
        candidates=["B", "A", "C"],  # greedy candidate B is the odd one out
    ))
    r = await run_pipeline(q, object())
    assert r.sql == "A" and r.complex and env.last_reasoning and env.last_n == 3
    assert r.agreement == pytest.approx(0.67, abs=0.01)


async def test_vote_tie_goes_to_greedy_candidate(install):
    install(FakeEnv({"A": qr([[1]]), "B": qr([[2]])}, candidates=["A", "B"]))
    r = await run_pipeline("for each category which film has the most rentals compared to the average", object())
    assert r.sql == "A"


async def test_one_failing_candidate_does_not_block_others(install):
    install(FakeEnv({"A": Exception("x"), "B": qr([[1]])}, candidates=["A", "B"]))
    r = await run_pipeline("for each category which film has the most rentals compared to the average", object())
    assert r.sql == "B" and r.attempts == 1


async def test_sql_cache_skips_llm_but_reruns_query(install):
    env = install(FakeEnv({"SELECT 1": qr([[1]])}, candidates=["SELECT 1"]))
    await run_pipeline("How many films?", object())
    again = await run_pipeline("how many films", object())  # different casing/punctuation
    assert again.cached and again.attempts == 0
    assert env.llm_calls["generate"] == 1          # LLM not called again
    assert env.executed == ["SELECT 1", "SELECT 1"]  # DB queried again → fresh data
    assert env.llm_calls["summarize"] == 1         # same result → cached answer


async def test_answer_regenerated_when_data_changes(install):
    env = install(FakeEnv({"SELECT 1": qr([[1]])}, candidates=["SELECT 1"]))
    await run_pipeline("how many films", object())
    env.db["SELECT 1"] = qr([[2]])
    r = await run_pipeline("how many films", object())
    assert r.cached and env.llm_calls["summarize"] == 2


async def test_broken_cached_sql_is_evicted_and_regenerated(install):
    env = install(FakeEnv({"OLD": qr([[1]]), "NEW": qr([[1]])}, candidates=["OLD"]))
    await run_pipeline("q one", object())
    env.db["OLD"] = Exception("relation gone")
    env.candidates = ["NEW"]
    r = await run_pipeline("q one", object())
    assert r.sql == "NEW" and not r.cached


async def test_empty_results_are_not_cached(install):
    env = install(FakeEnv({"SELECT 1": qr([])}, candidates=["SELECT 1"], judge=None))
    await run_pipeline("any films from mars", object())
    await run_pipeline("any films from mars", object())
    assert env.llm_calls["generate"] == 2


async def test_suspicious_empty_result_is_retried(install):
    env = install(FakeEnv(
        {"WRONG": qr([]), "RIGHT": qr([[5]])}, candidates=["WRONG"], corrections=["RIGHT"],
        judge="category names are capitalised",
    ))
    r = await run_pipeline("films in the action category", object())
    assert r.sql == "RIGHT" and r.attempts == 2


async def test_plausible_empty_result_is_kept(install):
    env = install(FakeEnv({"S": qr([])}, candidates=["S"], judge=None))
    r = await run_pipeline("films longer than 10000 minutes", object())
    assert r.row_count == 0 and env.llm_calls["correct"] == 0


async def test_followup_is_rewritten_with_history(install):
    env = install(FakeEnv({"S": qr([[1]])}, candidates=["S"]))
    r = await run_pipeline("and for Canada?", object(), history=[{"role": "user", "content": "top customers"}])
    assert r.standalone_question == "standalone: and for Canada?" and env.llm_calls["rewrite"] == 1


def test_result_signature_is_order_and_name_insensitive():
    assert result_signature(["x"], [[1], [2]]) == result_signature(["y"], [[2], [1]])
    assert result_signature(["x"], [[1.00001]]) == result_signature(["x"], [[1.0]])
    assert result_signature(["x"], [[1]]) != result_signature(["x"], [[2]])
    assert result_signature(["x"], [[1]]) != result_signature(["x", "y"], [[1, 1]])


@pytest.mark.parametrize("q,expected", [
    ("how many films are there", False),
    ("list all actors", False),
    ("show the top 3 customers by revenue in each country", True),
    ("which actors appeared in action films but never in horror films", True),
    ("show month over month revenue change", True),
    ("which customers spent more than the average customer", True),
    ("which films are longer than 120 minutes", False),
])
def test_is_complex(q, expected):
    assert is_complex(q) is expected
