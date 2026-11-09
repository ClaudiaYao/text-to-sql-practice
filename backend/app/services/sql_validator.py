"""
SQL validation using sqlglot — defence in depth in front of the read-only DB connection.

Accepts exactly one read-only statement: SELECT (with CTEs / subqueries) or a set operation
(UNION / INTERSECT / EXCEPT). Rejects DML/DDL anywhere in the tree (including writable CTEs),
SELECT INTO, system functions, system catalogs, and explicit references to blocked columns.
"""
import sqlglot
import sqlglot.errors
import sqlglot.expressions as exp

from app.constants import ALLOWED_SCHEMAS, BLOCKED_COLUMNS

_ROOT_TYPES = (exp.Select, exp.Union, exp.Intersect, exp.Except)

_FORBIDDEN_NODES = tuple(
    getattr(exp, name)
    for name in (
        "Insert", "Update", "Delete", "Merge", "Drop", "Create", "Alter", "AlterTable",
        "TruncateTable", "Command", "Set", "Into", "Lock", "Copy", "Grant", "Use",
    )
    if hasattr(exp, name)
)

_FORBIDDEN_FUNCTIONS = frozenset(
    {"set_config", "dblink", "lo_import", "lo_export", "lo_unlink", "nextval", "setval", "txid_current"}
)


def validate_sql(sql: str) -> str | None:
    """Return None if `sql` is one safe read-only query, else a human-readable error message."""
    if not sql or not sql.strip():
        return "SQL is empty."

    try:
        statements = sqlglot.parse(sql, dialect="postgres", error_level=sqlglot.ErrorLevel.RAISE)
    except sqlglot.errors.ParseError as exc:
        first = exc.errors[0] if exc.errors else {}
        msg = first.get("description", str(exc))
        return f"Syntax error at line {first.get('line', '?')}, col {first.get('col', '?')}: {msg}"
    except sqlglot.errors.SqlglotError as exc:
        return f"Could not parse SQL: {exc}"

    statements = [s for s in statements if s is not None]
    if not statements:
        return "No SQL statement could be parsed."
    if len(statements) > 1:
        return "Only a single SQL statement is allowed."

    stmt = statements[0]
    if not isinstance(stmt, _ROOT_TYPES):
        return f"Only SELECT queries are allowed; got {type(stmt).__name__.upper()}."

    for node in stmt.walk():
        node = node[0] if isinstance(node, tuple) else node
        if isinstance(node, _FORBIDDEN_NODES):
            return f"Forbidden operation in query: {type(node).__name__.upper()}."
        if isinstance(node, exp.Table):
            if (node.args.get("db") and node.db.lower() not in ALLOWED_SCHEMAS):
                return f"Access to schema '{node.db}' is not allowed."
        if isinstance(node, exp.Anonymous):
            name = node.name.lower()
            if name.startswith("pg_") or name in _FORBIDDEN_FUNCTIONS:
                return f"Function '{node.name}' is not allowed."
        if isinstance(node, exp.Column) and node.name.lower() in BLOCKED_COLUMNS:
            return f"Column '{node.name}' is not accessible."
    return None
