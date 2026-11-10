import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.main import app
from app.services.llm import LLMError, Unanswerable
from app.services.pipeline import PipelineError, PipelineResult

client = TestClient(app)  # no `with`: lifespan (DB warm-up) is not run


def _result(**kw):
    base = dict(
        sql="SELECT 1", columns=["a"], rows=[[1]], row_count=1, truncated=False, execution_ms=1.0,
        attempts=1, answer="One.", standalone_question="q",
    )
    base.update(kw)
    return PipelineResult(**base)


def patch(monkeypatch, outcome):
    async def fake(question, db, history=None):
        fake.calls.append((question, history))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    fake.calls = []
    monkeypatch.setattr(routes, "run_pipeline", fake)
    monkeypatch.setattr(routes, "get_db", lambda: None)
    app.dependency_overrides[routes.get_db] = lambda: None
    return fake


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.clear()


def test_query_ok(monkeypatch):
    fake = patch(monkeypatch, _result())
    r = client.post("/api/query", json={"question": "  how many films  "})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "One." and body["rows"] == [[1]] and body["cached"] is False
    assert fake.calls == [("how many films", None)]


def test_chat_passes_history(monkeypatch):
    fake = patch(monkeypatch, _result())
    r = client.post("/api/chat", json={"message": "and Canada?", "history": [{"role": "user", "content": "top customers"}]})
    assert r.status_code == 200
    assert fake.calls[0][1] == [{"role": "user", "content": "top customers"}]


def test_empty_question_is_400(monkeypatch):
    patch(monkeypatch, _result())
    assert client.post("/api/query", json={"question": "   "}).status_code == 400


@pytest.mark.parametrize(
    "exc,status",
    [
        (Unanswerable("cannot modify data"), 422),
        (PipelineError("failed", sql="SELECT x"), 400),
        (LLMError("throttled"), 502),
        (RuntimeError("boom"), 500),
    ],
)
def test_error_mapping(monkeypatch, exc, status):
    patch(monkeypatch, exc)
    r = client.post("/api/query", json={"question": "q"})
    assert r.status_code == status


def test_health_and_cache_endpoints():
    assert client.get("/health").json() == {"status": "ok"}
    stats = client.get("/api/cache/stats").json()
    assert {"sql", "answer", "enabled"} <= stats.keys()
    assert client.delete("/api/cache").json() == {"status": "cleared"}


def test_chat_is_stored_and_continues_conversation(monkeypatch):
    fake = patch(monkeypatch, _result(answer="Two."))
    first = client.post("/api/chat", json={"message": "top customers"}).json()
    cid = first["conversation_id"]
    assert cid
    client.post("/api/chat", json={"message": "and Canada?", "conversation_id": cid})
    # the server (not the client) supplied the history for turn 2
    assert fake.calls[1][1] == [
        {"role": "user", "content": "top customers"},
        {"role": "assistant", "content": "Two."},
    ]
    conv = client.get(f"/api/conversations/{cid}").json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant", "user", "assistant"]
    assert conv["messages"][1]["result"]["rows"] == [[1]] and conv["messages"][1]["result"]["sql"] == "SELECT 1"
    assert conv["title"] == "top customers"
    assert cid in [c["id"] for c in client.get("/api/conversations").json()]
    assert client.delete(f"/api/conversations/{cid}").json() == {"status": "deleted"}
    assert client.get(f"/api/conversations/{cid}").status_code == 404


def test_failed_turn_is_stored_and_excluded_from_context(monkeypatch):
    patch(monkeypatch, Unanswerable("cannot do that"))
    r = client.post("/api/chat", json={"message": "delete everything"})
    assert r.status_code == 422 and r.json()["detail"] == "cannot do that"
    cid = r.json()["conversation_id"]
    msgs = client.get(f"/api/conversations/{cid}").json()["messages"]
    assert msgs[1]["error"] == "cannot do that" and msgs[1]["result"] is None
    fake = patch(monkeypatch, _result())
    client.post("/api/chat", json={"message": "how many films", "conversation_id": cid})
    assert fake.calls[0][1] is None  # failed turn is not fed back as context


def test_unknown_conversation_is_404(monkeypatch):
    patch(monkeypatch, _result())
    r = client.post("/api/chat", json={"message": "q", "conversation_id": "nope"})
    assert r.status_code == 404
