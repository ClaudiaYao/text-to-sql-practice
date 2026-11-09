import pytest

from app.services.sql_validator import validate_sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM film",
        "SELECT title FROM film WHERE title ILIKE '%a:b%' ORDER BY title LIMIT 5",
        "WITH t AS (SELECT customer_id, SUM(amount) s FROM payment GROUP BY 1) SELECT * FROM t WHERE s > 10",
        "SELECT actor_id FROM film_actor INTERSECT SELECT actor_id FROM actor",
        "SELECT actor_id FROM actor EXCEPT SELECT actor_id FROM film_actor",
        "SELECT 1 UNION ALL SELECT 2",
        "SELECT DATE_TRUNC('month', rental_date), COUNT(*) FROM rental GROUP BY 1",
        "SELECT rating, RANK() OVER (PARTITION BY rating ORDER BY length DESC) FROM film",
        "SELECT * FROM public.film",
    ],
)
def test_accepts_read_only(sql):
    assert validate_sql(sql) is None


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "   ",
        "DELETE FROM customer",
        "UPDATE film SET title = 'x'",
        "INSERT INTO actor(first_name) VALUES ('x')",
        "DROP TABLE film",
        "TRUNCATE film",
        "SELECT 1; DROP TABLE film",
        "SELECT 1; SELECT 2",
        "SELECT * INTO newtable FROM film",
        "WITH d AS (DELETE FROM film RETURNING *) SELECT * FROM d",
        "SELECT pg_sleep(100)",
        "SELECT * FROM pg_catalog.pg_tables",
        "SELECT * FROM information_schema.tables",
        "SELECT password FROM staff",
        "SELEC title FROM film",
        "SELECT title FROM film WHERE",
    ],
)
def test_rejects_unsafe_or_broken(sql):
    assert validate_sql(sql) is not None
