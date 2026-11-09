import pytest

from app.services.llm import Unanswerable, parse_response


def test_plain_sql_tag():
    c = parse_response("<sql>SELECT 1;</sql>")
    assert c.sql == "SELECT 1" and c.plan == ""


def test_plan_and_sql():
    c = parse_response("<plan>\n1. film\n</plan>\n<sql>\nSELECT * FROM film\n</sql>")
    assert c.sql == "SELECT * FROM film" and "film" in c.plan


def test_markdown_fence_fallback():
    assert parse_response("```sql\nSELECT 1\n```").sql == "SELECT 1"


def test_unclosed_sql_tag_when_truncated():
    assert parse_response("<sql>SELECT a FROM b").sql == "SELECT a FROM b"


def test_error_signal():
    with pytest.raises(Unanswerable, match="no such data"):
        parse_response("ERROR: no such data")
    with pytest.raises(Unanswerable):
        parse_response("<sql>ERROR: cannot modify data</sql>")


def test_select_mentioning_error_is_not_an_error_signal():
    assert parse_response("<sql>SELECT 'ERROR: x' AS m</sql>").sql.startswith("SELECT")
