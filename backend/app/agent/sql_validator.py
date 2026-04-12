"""
SQL validation using sqlglot.

Catches syntax errors and non-SELECT statements before they hit the database,
saving a round-trip and giving the self-correction loop a cleaner error message.
"""
import sqlglot
import sqlglot.errors
import sqlglot.expressions as exp


def validate_sql(sql: str) -> str | None:
    """
    Parse and validate a SQL string.

    Returns None if the SQL is a valid SELECT statement.
    Returns a human-readable error string if validation fails.
    """
    if not sql or not sql.strip():
        return "SQL is empty."

    try:
        statements = sqlglot.parse(sql, dialect="postgres", error_level=sqlglot.ErrorLevel.RAISE)
    except sqlglot.errors.ParseError as exc:
        # sqlglot gives a list of errors; surface the first one cleanly
        first = exc.errors[0] if exc.errors else {}
        line = first.get("line", "?")
        col = first.get("col", "?")
        msg = first.get("description", str(exc))
        return f"Syntax error at line {line}, col {col}: {msg}"

    if not statements or statements[0] is None:
        return "No SQL statement could be parsed."

    stmt = statements[0]

    # Enforce SELECT-only (no DML/DDL)
    if not isinstance(stmt, exp.Select):
        kind = type(stmt).__name__.upper()
        return f"Only SELECT statements are allowed; got {kind}."

    return None
