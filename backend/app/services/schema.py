"""
Live schema introspection (tables, PKs, FKs, enums, small-table value hints), cached with a TTL.

The full schema of a database this size is a few thousand tokens, so it is sent whole: schema
retrieval can only lose information (a missed table = a wrong query), never add accuracy.
"""
import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import BLOCKED_COLUMNS, HIDDEN_COLUMNS, HIDDEN_TABLES

logger = logging.getLogger(__name__)

_SENSITIVE_HINT_COLUMNS = re.compile(r"password|email|username|picture|phone", re.IGNORECASE)
_HINT_MAX_VALUES = 30


@dataclass(frozen=True)
class SchemaContext:
    text: str
    hash: str


_cache: SchemaContext | None = None
_cache_expires = 0.0
_lock = asyncio.Lock()


async def get_schema_context(db: AsyncSession, force: bool = False) -> SchemaContext:
    global _cache, _cache_expires
    if not force and _cache is not None and time.time() < _cache_expires:
        return _cache
    async with _lock:
        if not force and _cache is not None and time.time() < _cache_expires:
            return _cache
        description = await _introspect(db)
        _cache = SchemaContext(description, hashlib.sha256(description.encode()).hexdigest()[:12])
        _cache_expires = time.time() + settings.schema_cache_ttl_seconds
        logger.info("[schema] introspected: %d chars, hash=%s", len(description), _cache.hash)
        return _cache


def invalidate_schema_cache() -> None:
    global _cache
    _cache = None


async def _introspect(db: AsyncSession) -> str:
    await db.rollback()
    try:
        tables = (
            await db.execute(
                text(
                    """
                    SELECT c.relname FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND NOT c.relispartition
                      AND NOT EXISTS (SELECT 1 FROM pg_inherits i WHERE i.inhrelid = c.oid)
                    ORDER BY c.relname
                    """
                )
            )
        ).scalars().all()

        col_rows = (
            await db.execute(
                text(
                    """
                    SELECT table_name, column_name, data_type, udt_name, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                    ORDER BY table_name, ordinal_position
                    """
                )
            )
        ).all()

        pk_rows = (
            await db.execute(
                text(
                    """
                    SELECT c.conrelid::regclass::text, a.attname
                    FROM pg_constraint c
                    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
                    WHERE c.contype = 'p' AND c.connamespace = 'public'::regnamespace
                    """
                )
            )
        ).all()

        fk_rows = (
            await db.execute(
                text(
                    """
                    SELECT c.conrelid::regclass::text, a.attname, c.confrelid::regclass::text, af.attname
                    FROM pg_constraint c
                    JOIN LATERAL unnest(c.conkey, c.confkey) AS k(attnum, fattnum) ON true
                    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
                    JOIN pg_attribute af ON af.attrelid = c.confrelid AND af.attnum = k.fattnum
                    WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace
                    ORDER BY 1, 2
                    """
                )
            )
        ).all()

        enum_rows = (
            await db.execute(
                text(
                    """
                    SELECT t.typname, e.enumlabel FROM pg_type t
                    JOIN pg_enum e ON e.enumtypid = t.oid
                    JOIN pg_namespace n ON n.oid = t.typnamespace
                    WHERE n.nspname = 'public' ORDER BY t.typname, e.enumsortorder
                    """
                )
            )
        ).all()
    finally:
        await db.rollback()

    tables = [t for t in tables if t not in HIDDEN_TABLES]
    table_set = set(tables)
    pks: dict[str, set[str]] = {}
    for table, col in pk_rows:
        pks.setdefault(table, set()).add(col)

    cols: dict[str, list[tuple[str, str, str]]] = {}
    for table, col, dtype, udt, nullable in col_rows:
        if table not in table_set or col.lower() in BLOCKED_COLUMNS | HIDDEN_COLUMNS:
            continue
        type_name = _short_type(dtype, udt)
        cols.setdefault(table, []).append((col, type_name, nullable))

    lines = ["TABLES (PK = primary key)"]
    for table in tables:
        parts = []
        for col, type_name, nullable in cols.get(table, []):
            flag = " PK" if col in pks.get(table, set()) else ""
            null = " NULL" if nullable == "YES" and not flag else ""
            parts.append(f"{col} {type_name}{flag}{null}")
        lines.append(f"{table}({', '.join(parts)})")

    fks = [r for r in fk_rows if r[0] in table_set and r[2] in table_set]
    if fks:
        lines += ["", "FOREIGN KEYS (join along these)"]
        lines += [f"{a}.{b} -> {c}.{d}" for a, b, c, d in fks]

    enums: dict[str, list[str]] = {}
    for name, label in enum_rows:
        enums.setdefault(name, []).append(label)
    if enums:
        lines += ["", "ENUM VALUES"]
        lines += [f"{name}: {', '.join(repr(v) for v in labels)}" for name, labels in enums.items()]

    hints = await _value_hints(db, tables, cols)
    if hints:
        lines += ["", "VALUE HINTS (complete value lists for small lookup tables)"]
        lines += hints
    return "\n".join(lines)


_TEXT_TYPES = ("text", "varchar", "char")
_TYPE_ALIASES = {
    "character varying": "varchar",
    "character": "char",
    "timestamp without time zone": "timestamp",
    "timestamp with time zone": "timestamptz",
    "double precision": "float8",
}


def _short_type(data_type: str, udt_name: str) -> str:
    if data_type == "USER-DEFINED":
        return udt_name
    if data_type == "ARRAY":
        return f"{_TYPE_ALIASES.get(udt_name.lstrip('_'), udt_name.lstrip('_'))}[]"
    return _TYPE_ALIASES.get(data_type, data_type)


async def _value_hints(db: AsyncSession, tables: list[str], cols: dict) -> list[str]:
    """List the distinct values of text columns that turn out to have few values (e.g. category.name)."""
    hints: list[str] = []
    for table in tables:
        for col, type_name, _ in cols.get(table, []):
            if type_name not in _TEXT_TYPES or _SENSITIVE_HINT_COLUMNS.search(col):
                continue
            try:
                rows = (
                    await db.execute(
                        text(f'SELECT DISTINCT "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL LIMIT :n'),
                        {"n": _HINT_MAX_VALUES + 1},
                    )
                ).scalars().all()
            except Exception:
                continue
            finally:
                await db.rollback()
            values = sorted({str(v).strip() for v in rows if str(v).strip()})  # char(n) columns are blank-padded
            if 0 < len(values) <= _HINT_MAX_VALUES and len(rows) <= _HINT_MAX_VALUES:
                hints.append(f"{table}.{col}: {', '.join(repr(v) for v in values)}")
    return hints
