"""All prompt templates. Edit rules here; never hardcode schema anywhere else."""

_RULES = """\
RULES
1. Only read-only queries: SELECT, CTEs (WITH) and set operations (UNION/INTERSECT/EXCEPT). Never modify
   data or call system functions. If the user asks to change data, or the question cannot be answered from
   this schema, answer exactly `ERROR: <short reason>` instead of SQL.
2. Use only tables and columns that appear in the schema, spelled exactly. Join only along the listed
   foreign keys; never guess a join column.
3. Count carefully. When joins can multiply rows, use COUNT(DISTINCT <id>) or pre-aggregate in a CTE
   before joining. Group and join on ids (names are not unique), then also show the name columns.
4. Return what was asked: identifying columns (id + name/title) plus the requested metric(s), with clear
   aliases. No unrelated columns.
5. "Top/best/most N" -> ORDER BY the metric DESC with a stable tie-breaker (an id), LIMIT N.
   A singular "the most / the highest" (no N) must include ties: compare with MAX(...) or use RANK() = 1.
6. Text filters: use ILIKE / LOWER() — names and titles are stored in UPPERCASE. Check VALUE HINTS and
   ENUM VALUES for the exact spelling of categories, ratings, languages.
7. Dates: use DATE_TRUNC / EXTRACT. For relative phrases anchor on MAX(date) in the data, not CURRENT_DATE.
8. Guard divisions with NULLIF(x, 0); round money/percentages to 2 decimals; cast to ::numeric before ROUND.
9. Do not add a LIMIT unless the question asks for a top-N / sample (the system caps rows itself).
10. No trailing semicolon, no comments inside the SQL."""

_FORMAT_SIMPLE = "Reply with the SQL only, wrapped in <sql>...</sql> (or `ERROR: <reason>`)."

_FORMAT_REASONING = """\
Reply in exactly this form (or `ERROR: <reason>`):
<plan>
at most 8 short lines: (1) tables needed, (2) join path, (3) filters, (4) aggregation grain and any
fan-out risk, (5) window functions / CTEs needed, (6) ordering & limit, (7) assumptions you made
</plan>
<sql>
the final query
</sql>"""


def _context(schema: str, notes: str, examples: list[dict]) -> str:
    parts = [
        "DATABASE SCHEMA (PostgreSQL, Sakila DVD-rental)\n" + schema,
        "DOMAIN NOTES\n" + notes,
    ]
    if examples:
        shots = "\n\n".join(f"Question: {e['question']}\nSQL: {e['sql']}" for e in examples)
        parts.append("WORKED EXAMPLES (verified; mimic their style and techniques)\n" + shots)
    return "\n\n".join(parts)


def generation_system(schema: str, notes: str, examples: list[dict], reasoning: bool) -> str:
    return (
        "You are a senior PostgreSQL analyst. Convert the user's question into one exact, "
        "read-only PostgreSQL query for the database below.\n\n"
        + _context(schema, notes, examples)
        + "\n\n"
        + _RULES
        + "\n\n"
        + (_FORMAT_REASONING if reasoning else _FORMAT_SIMPLE)
    )


def correction_system(schema: str, notes: str, examples: list[dict], reasoning: bool) -> str:
    return (
        "You are a senior PostgreSQL analyst fixing a query that failed or looks wrong. Fix the exact "
        "problem described, keep what was right, and make sure the result truly answers the question.\n\n"
        + _context(schema, notes, examples)
        + "\n\n"
        + _RULES
        + "\n\n"
        + (_FORMAT_REASONING if reasoning else _FORMAT_SIMPLE)
    )


def correction_user(question: str, failed_sql: str, problem: str, previous: list[str]) -> str:
    tried = ""
    if previous:
        tried = "Earlier attempts that did NOT work (do not repeat them):\n" + "\n".join(
            f"- {s}" for s in previous
        ) + "\n\n"
    return (
        f'Question: "{question}"\n\nLatest SQL:\n{failed_sql}\n\nProblem:\n{problem}\n\n{tried}'
        "Return the corrected query."
    )


REWRITE_SYSTEM = """\
You rewrite a follow-up message in a chat about a DVD-rental database into ONE standalone question that
can be understood without the chat history. Resolve pronouns and omitted context ("those", "now only
Canada", "and by store?"). If the message is already standalone, return it unchanged. Output only the
question text, nothing else."""


def rewrite_user(question: str, history: list[dict]) -> str:
    convo = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in history)
    return f"Chat history:\n{convo}\n\nFollow-up message: {question}\n\nStandalone question:"


JUDGE_EMPTY_SYSTEM = """\
You review a SQL query that returned ZERO rows for a question about a DVD-rental database.
Decide if an empty result is a plausible, correct answer, or if the query is probably wrong (wrong
filter value or case, wrong join, over-restrictive condition, wrong table).
Reply with exactly `OK` if empty is plausible, otherwise `RETRY: <one sentence on what to fix>`.

{context}"""


def judge_empty_user(question: str, sql: str) -> str:
    return f'Question: "{question}"\n\nSQL:\n{sql}\n\nVerdict:'


def judge_empty_system(schema: str, notes: str) -> str:
    return JUDGE_EMPTY_SYSTEM.format(context=_context(schema, notes, []))


ANSWER_SYSTEM = """\
You answer a user's question about a DVD-rental database using ONLY the query result provided.
- 1 to 4 sentences, plain language, lead with the direct answer.
- Quote specific names and numbers exactly as they appear in the data; never invent or estimate values.
- If many rows were returned, summarise (top items, totals, row count) instead of listing everything.
- If the result says rows were truncated, say only the first rows were returned.
- Do not mention SQL, tables or columns unless it helps the user."""


def answer_user(question: str, columns: list[str], rows: list[list], row_count: int, truncated: bool) -> str:
    header = ", ".join(columns)
    body = "\n".join(", ".join("" if v is None else str(v) for v in r) for r in rows)
    more = f"\n(Showing {len(rows)} of {row_count}{'+' if truncated else ''} rows.)" if len(rows) < row_count or truncated else ""
    return (
        f'Question: "{question}"\n\nResult ({row_count} row{"s" if row_count != 1 else ""}'
        f"{', truncated' if truncated else ''}):\n{header}\n{body}{more}\n\nAnswer:"
    )
