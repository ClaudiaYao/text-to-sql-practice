"""
Few-shot example selection — no embeddings needed.

Examples come from data/seed/sakila_examples.json. For each question we rank them by keyword
overlap with the question text plus "technique hints" derived from each example's SQL
(window function, CTE, EXCEPT, NOT EXISTS, ...), so a question containing "never" or "rank" is
matched to examples that demonstrate that technique, not just ones that share table words.
Cost is negligible, deterministic and easy to debug. If the example bank ever outgrows the
prompt (100+), swap `select_examples` for embedding retrieval behind the same signature.
"""
import json
import math
import re
from functools import lru_cache

from app.config import BACKEND_DIR

_SEED_PATH = BACKEND_DIR / "data" / "seed" / "sakila_examples.json"

_STOPWORDS = frozenset(
    "a an the of in on for to and or is are was were be been by with from at as that this these those "
    "show me list give find what which who whom how many much do does did have has had all any each "
    "please tell get display return their there its it".split()
)

# SQL feature -> question words that call for it
_TECHNIQUES = [
    (r"\bOVER\s*\(", "rank ranking top each per within partition running cumulative lag previous change over window"),
    (r"\bPARTITION BY\b", "each per within group"),
    (r"\bWITH\b.*\bAS\s*\(", "compare versus average than more above below cte step"),
    (r"\bINTERSECT\b", "both and common also"),
    (r"\bEXCEPT\b", "but not never without excluding only"),
    (r"NOT EXISTS|NOT IN|IS NULL", "never not without no none missing unreturned"),
    (r"\bHAVING\b", "more than at least fewer least minimum"),
    (r"DATE_TRUNC|EXTRACT", "month year week day date time monthly yearly daily trend"),
    (r"\bILIKE\b|\bLIKE\b", "contains containing title name like starts"),
    (r"\bLIMIT\b", "top best most highest lowest"),
    (r"COUNT\(DISTINCT", "distinct unique different"),
    (r"\(SELECT\b.*\bFROM\b", "average overall above below than"),
    (r"100\.0", "percentage percent share proportion ratio"),
]


def _tokens(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9']+", text.lower()):
        if w in _STOPWORDS:
            continue
        if len(w) > 3 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return out


def _technique_tokens(sql: str) -> set[str]:
    out: set[str] = set()
    for pattern, words in _TECHNIQUES:
        if re.search(pattern, sql, flags=re.IGNORECASE | re.DOTALL):
            out |= _tokens(words)
    return out


@lru_cache(maxsize=1)
def load_examples() -> tuple[dict, ...]:
    with open(_SEED_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    prepared = []
    for ex in raw:
        q_tokens = _tokens(ex["question"])
        prepared.append(
            {
                "question": ex["question"],
                "sql": ex["sql"],
                "_q": q_tokens,
                "_t": _technique_tokens(ex["sql"]),
            }
        )
    return tuple(prepared)


def select_examples(question: str, k: int) -> list[dict]:
    """Return the k most relevant {"question", "sql"} examples for the question (best first)."""
    if k <= 0:
        return []
    q = _tokens(question)
    if not q:
        return []
    scored = []
    for idx, ex in enumerate(load_examples()):
        topic = len(q & ex["_q"]) / math.sqrt(len(q) * len(ex["_q"]) or 1)
        technique = len(q & ex["_t"]) / math.sqrt(len(q) * len(ex["_t"]) or 1)
        scored.append((topic + 0.6 * technique, -idx, ex))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [{"question": e["question"], "sql": e["sql"]} for s, _, e in scored[:k] if s > 0]
