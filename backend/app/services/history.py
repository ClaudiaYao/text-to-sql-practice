"""Server-side chat history in SQLite (stdlib; one file, no extra service).

Tables: `conversations` and `messages`. An assistant message stores the whole query result
(SQL, columns, rows, metadata) as JSON in `result`, so the UI can replay a conversation exactly.
Calls are blocking sqlite3 wrapped in `asyncio.to_thread`; one short-lived connection per call.
"""
import asyncio
import json
import logging
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone

from app.config import BACKEND_DIR, settings

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    error           TEXT,
    result          TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);
"""

TITLE_MAX = 60


def _path() -> str:
    path = settings.history_db_path.strip() or "data/history/history.sqlite3"
    return path if os.path.isabs(path) else str(BACKEND_DIR / path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    path = _path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)  # idempotent; keeps start-up and tests free of a separate init step
    return conn


def _title(question: str) -> str:
    q = " ".join(question.split())
    return q if len(q) <= TITLE_MAX else q[: TITLE_MAX - 1] + "…"


# ── blocking implementations ───────────────────────────────────────────────
def _exists(conversation_id: str) -> bool:
    with closing(_connect()) as c:
        return c.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone() is not None


def _recent_messages(conversation_id: str, limit: int) -> list[dict]:
    """Last `limit` successful messages as {role, content}, oldest first (failed turns are skipped)."""
    with closing(_connect()) as c:
        rows = c.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? AND error IS NULL "
            "ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def _save_turn(
    conversation_id: str | None, question: str, answer: str, result: dict | None, error: str | None
) -> str:
    now = _now()
    with closing(_connect()) as c, c:  # `with c` = one transaction
        if conversation_id is None:
            conversation_id = uuid.uuid4().hex
            c.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conversation_id, _title(question), now, now),
            )
        else:
            c.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        c.execute(
            "INSERT INTO messages (conversation_id, role, content, error, created_at) VALUES (?, 'user', ?, ?, ?)",
            (conversation_id, question, error, now),  # a failed turn marks both rows, so neither is reused as context
        )
        c.execute(
            "INSERT INTO messages (conversation_id, role, content, error, result, created_at) "
            "VALUES (?, 'assistant', ?, ?, ?, ?)",
            (conversation_id, answer, error, json.dumps(result, default=str) if result else None, now),
        )
    return conversation_id


def _list() -> list[dict]:
    with closing(_connect()) as c:
        rows = c.execute(
            "SELECT c.id, c.title, c.created_at, c.updated_at, COUNT(m.id) AS message_count "
            "FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id "
            "GROUP BY c.id ORDER BY c.updated_at DESC, c.rowid DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def _get(conversation_id: str) -> dict | None:
    with closing(_connect()) as c:
        conv = c.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if conv is None:
            return None
        msgs = c.execute(
            "SELECT id, role, content, error, result, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
    messages = []
    for m in msgs:
        d = dict(m)
        d["result"] = json.loads(d["result"]) if d["result"] else None
        messages.append(d)
    return {**dict(conv), "message_count": len(messages), "messages": messages}


def _delete(conversation_id: str) -> bool:
    with closing(_connect()) as c, c:
        return c.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,)).rowcount > 0


# ── async API ──────────────────────────────────────────────────────────────
async def conversation_exists(conversation_id: str) -> bool:
    return await asyncio.to_thread(_exists, conversation_id)


async def recent_messages(conversation_id: str, limit: int = 20) -> list[dict]:
    return await asyncio.to_thread(_recent_messages, conversation_id, limit)


async def save_turn(
    conversation_id: str | None,
    question: str,
    answer: str,
    result: dict | None = None,
    error: str | None = None,
) -> str:
    """Persist one user question + assistant reply (creating the conversation if needed); returns its id."""
    return await asyncio.to_thread(_save_turn, conversation_id, question, answer, result, error)


async def list_conversations() -> list[dict]:
    return await asyncio.to_thread(_list)


async def get_conversation(conversation_id: str) -> dict | None:
    return await asyncio.to_thread(_get, conversation_id)


async def delete_conversation(conversation_id: str) -> bool:
    return await asyncio.to_thread(_delete, conversation_id)
