"""
Execution-accuracy scoring: is the generated result set the same answer as the reference result set?

Rules (chosen to reject wrong answers but not penalise harmless presentation differences):
  * Column names are ignored; every reference column must be present in the generated result
    (matched by its values). Extra generated columns (e.g. an id next to a name) are allowed.
  * Rows are compared as a multiset unless the case is `ordered`, then as a sequence.
  * Integers must match exactly; non-integers match within 0.011 (rounding differences); text ignores char(n) padding
    and surrounding whitespace; timestamps at midnight match plain dates; 'YYYY-MM' matches the
    first day of that month.
  * Both results empty counts as a match.
"""
import re
from dataclasses import dataclass

_DATE = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?(?:[T ](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?)?$")


@dataclass
class Verdict:
    correct: bool
    reason: str = ""
    extra_columns: int = 0


def _norm(v):
    if isinstance(v, str):
        s = v.strip()
        m = _DATE.match(s)
        if m:
            y, mo, d, hh, mm, ss = m.groups()
            out = f"{y}-{mo}-{d or '01'}"
            if hh and (hh, mm, ss) != ("00", "00", "00"):
                out += f"T{hh}:{mm}:{ss}"
            return out
        return s
    return v  # None, bool, int, float are compared in _eq


def _eq(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if isinstance(a, int) and isinstance(b, int):
            return a == b  # counts and ids must match exactly
        return abs(a - b) <= 0.011  # rounding of averages / sums / percentages
    return a == b


def _rows_eq(r1, r2) -> bool:
    return len(r1) == len(r2) and all(_eq(a, b) for a, b in zip(r1, r2))


def _multiset_eq(a: list, b: list) -> bool:
    """Order-insensitive row-list comparison with numeric tolerance (O(n²), n is capped by MAX_ROWS)."""
    if len(a) != len(b):
        return False
    remaining = list(b)
    for row in a:
        for i, cand in enumerate(remaining):
            if _rows_eq(row, cand):
                del remaining[i]
                break
        else:
            return False
    return True


def _column(rows: list[list], i: int) -> list[list]:
    return [[r[i]] for r in rows]


def compare_results(ref_rows: list[list], gen_rows: list[list], ordered: bool = False) -> Verdict:
    """Compare a generated result set against the reference one."""
    if not ref_rows and not gen_rows:
        return Verdict(True, "both empty")
    if len(ref_rows) != len(gen_rows):
        return Verdict(False, f"row count differs: expected {len(ref_rows)}, got {len(gen_rows)}")

    ref = [[_norm(v) for v in r] for r in ref_rows]
    gen = [[_norm(v) for v in r] for r in gen_rows]
    k, m = len(ref[0]), len(gen[0])
    if m < k:
        return Verdict(False, f"too few columns: expected {k}, got {m}")

    # candidate generated columns for each reference column (same values, ignoring order)
    candidates: list[list[int]] = []
    for j in range(k):
        rc = _column(ref, j)
        cands = [i for i in range(m) if _multiset_eq(rc, _column(gen, i))]
        if not cands:
            return Verdict(False, f"expected column #{j + 1} values not found in the result")
        candidates.append(cands)

    def projection_matches(cols: tuple[int, ...]) -> bool:
        proj = [[row[i] for i in cols] for row in gen]
        if ordered:
            return all(_rows_eq(x, y) for x, y in zip(ref, proj))
        return _multiset_eq(ref, proj)

    # Try every one-to-one column mapping (handles reference columns with identical values).
    def search(j: int, used: tuple[int, ...]) -> bool:
        if j == k:
            return projection_matches(used)
        return any(search(j + 1, used + (i,)) for i in candidates[j] if i not in used)

    if search(0, ()):
        return Verdict(True, "match" + (" (extra columns)" if m > k else ""), extra_columns=m - k)
    return Verdict(False, "ordering differs" if ordered else "rows differ although each column's values match")
