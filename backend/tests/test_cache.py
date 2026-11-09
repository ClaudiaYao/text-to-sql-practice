import json

from app.services.cache import TTLCache, make_key, normalize_question


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_normalize_collapses_trivial_differences():
    a = normalize_question("Show the TOP 10 customers by revenue?")
    assert a == normalize_question("  show the top 10 customers by revenue ")
    assert normalize_question("Please, show me X!") == normalize_question("show me x")
    assert normalize_question("top 10 customers") != normalize_question("top 5 customers")


def test_make_key_depends_on_all_parts():
    assert make_key("a", "b") == make_key("a", "b")
    assert make_key("a", "b") != make_key("a", "c")
    assert make_key("ab", "c") != make_key("a", "bc")


def test_ttl_expiry_and_stats():
    clock = Clock()
    c = TTLCache("t", 10, 60, clock=clock)
    c.set("k", "v")
    assert c.get("k") == "v"
    clock.t += 61
    assert c.get("k") is None
    s = c.stats()
    assert s["hits"] == 1 and s["misses"] == 1 and s["size"] == 0


def test_lru_eviction():
    c = TTLCache("t", 2, 60)
    c.set("a", 1)
    c.set("b", 2)
    c.get("a")  # a is now most recent
    c.set("c", 3)  # evicts b
    assert c.get("a") == 1 and c.get("b") is None and c.get("c") == 3


def test_persistence_round_trip_and_expiry(tmp_path):
    path = str(tmp_path / "sub" / "cache.json")
    clock = Clock()
    c1 = TTLCache("t", 10, 60, persist_path=path, clock=clock)
    c1.set("k", "SELECT 1")
    assert json.load(open(path))["k"][1] == "SELECT 1"

    c2 = TTLCache("t", 10, 60, persist_path=path, clock=clock)
    assert c2.get("k") == "SELECT 1"

    clock.t += 120
    c3 = TTLCache("t", 10, 60, persist_path=path, clock=clock)
    assert c3.get("k") is None


def test_corrupt_persist_file_is_ignored(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{not json")
    assert len(TTLCache("t", 10, 60, persist_path=str(path))) == 0
