import json

from app.config import BACKEND_DIR
from app.services.examples import select_examples
from app.services.sql_validator import validate_sql


def test_every_seed_example_passes_the_validator():
    data = json.load(open(BACKEND_DIR / "data" / "seed" / "sakila_examples.json"))
    assert len(data) >= 25
    for ex in data:
        assert validate_sql(ex["sql"]) is None, (ex["question"], validate_sql(ex["sql"]))


def test_topic_match():
    qs = [e["question"] for e in select_examples("top customers by total payment", 3)]
    assert any("customers by total payment" in q for q in qs)


def test_technique_match_for_set_difference():
    qs = [e["question"] for e in select_examples("actors who played in comedy but never in drama", 3)]
    assert any("never in Horror" in q for q in qs)


def test_k_zero_and_empty():
    assert select_examples("anything", 0) == []
    assert select_examples("", 3) == []
