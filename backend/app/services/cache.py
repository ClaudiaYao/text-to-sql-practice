"""
Caches for frequent questions.

What is cached, and why it is safe:
  sql_cache     normalised question (+ schema hash) → validated SQL.
                The SQL is re-executed on every hit, so results are always fresh; only the
                expensive LLM generation is skipped. A cached SQL that later fails is evicted.
                Optionally persisted to disk so it survives restarts.
  answer_cache  (question, result signature) → natural-language answer.
                Keyed on the actual result, so the answer is regenerated if the data changed.
  schema cache  lives in services/schema.py (TTL).
"""
import hashlib
import json
import logging
import os
import re
import tempfile
import time
from collections import OrderedDict
from typing import Any, Callable

from app.config import settings

logger = logging.getLogger(__name__)

_FILLER_PREFIX = re.compile(r"^(please |can you |could you |kindly )+", re.IGNORECASE)


def normalize_question(question: str) -> str:
    """Lower-case, strip punctuation and filler so trivially different phrasings share a key."""
    q = question.lower().strip()
    q = re.sub(r"[^\w\s']", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return _FILLER_PREFIX.sub("", q).strip()


def make_key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]


class TTLCache:
    """Small LRU + TTL cache with hit/miss stats and optional JSON persistence (values must be JSON-able)."""

    def __init__(
        self,
        name: str,
        max_entries: int,
        ttl_seconds: int,
        persist_path: str | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.name = name
        self.max_entries = max_entries
        self.ttl = ttl_seconds
        self.persist_path = persist_path or None
        self._clock = clock
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self.hits = 0
        self.misses = 0
        self._load()

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None or item[0] <= self._clock():
            if item is not None:
                del self._data[key]
                self._save()
            self.misses += 1
            return None
        self._data.move_to_end(key)
        self.hits += 1
        return item[1]

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (self._clock() + self.ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)
        self._save()

    def delete(self, key: str) -> None:
        if self._data.pop(key, None) is not None:
            self._save()

    def clear(self) -> None:
        self._data.clear()
        self.hits = self.misses = 0
        self._save()

    def __len__(self) -> int:
        return len(self._data)

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "name": self.name,
            "size": len(self._data),
            "max_entries": self.max_entries,
            "ttl_seconds": self.ttl,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
            "persisted": bool(self.persist_path),
        }

    # ── persistence ──────────────────────────────────────────────────────────
    def _load(self) -> None:
        if not self.persist_path or not os.path.exists(self.persist_path):
            return
        try:
            with open(self.persist_path, encoding="utf-8") as f:
                raw = json.load(f)
            now = self._clock()
            for key, (expires, value) in raw.items():
                if expires > now:
                    self._data[key] = (expires, value)
            logger.info("[cache:%s] loaded %d entries from %s", self.name, len(self._data), self.persist_path)
        except Exception:
            logger.exception("[cache:%s] could not load %s — starting empty", self.name, self.persist_path)

    def _save(self) -> None:
        if not self.persist_path:
            return
        try:
            directory = os.path.dirname(self.persist_path) or "."
            os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({k: [exp, v] for k, (exp, v) in self._data.items()}, f)
            os.replace(tmp, self.persist_path)  # atomic
        except Exception:
            logger.exception("[cache:%s] could not persist to %s", self.name, self.persist_path)


def _persist_path() -> str | None:
    path = settings.cache_persist_path.strip()
    if not path:
        return None
    from app.config import BACKEND_DIR

    return path if os.path.isabs(path) else str(BACKEND_DIR / path)


sql_cache = TTLCache(
    "sql", settings.cache_max_entries, settings.sql_cache_ttl_seconds, persist_path=_persist_path()
)
answer_cache = TTLCache("answer", settings.cache_max_entries, settings.answer_cache_ttl_seconds)


def cache_stats() -> dict:
    return {"enabled": settings.cache_enabled, "sql": sql_cache.stats(), "answer": answer_cache.stats()}


def clear_caches() -> None:
    sql_cache.clear()
    answer_cache.clear()
