"""Unit tests need no AWS; DB-marked tests use the real backend/.env database and skip if it is down."""
import os
import tempfile
from pathlib import Path

import pytest

_FORCED = {  # deterministic behaviour for unit tests regardless of the developer's .env
    "MAX_ROWS": "500",
    "MAX_ATTEMPTS": "3",
    "FEWSHOT_TOP_K": "4",
    "COMPLEX_CANDIDATES": "3",
    "CANDIDATE_TEMPERATURE": "0.7",
    "CACHE_ENABLED": "true",
    "CACHE_MAX_ENTRIES": "100",
    "SQL_CACHE_TTL_SECONDS": "3600",
    "ANSWER_CACHE_TTL_SECONDS": "3600",
    "SCHEMA_CACHE_TTL_SECONDS": "3600",
    "CACHE_PERSIST_PATH": "",
    "CORS_ORIGINS": "http://localhost:5173",
    "HISTORY_DB_PATH": os.path.join(tempfile.mkdtemp(prefix="t2s-history-"), "history.sqlite3"),
}
_DEFAULTS = {  # only used when there is no backend/.env (e.g. CI)
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/test",
    "AWS_REGION": "us-east-1",
    "BEDROCK_MODEL_ID": "test-model",
    "QUERY_TIMEOUT_MS": "10000",
}
os.environ.update(_FORCED)
if not (Path(__file__).resolve().parent.parent / ".env").exists():
    for _k, _v in _DEFAULTS.items():
        os.environ.setdefault(_k, _v)


@pytest.fixture(scope="session")
async def db_session_factory():
    """Real database session factory, or skip the test if Postgres is unreachable."""
    from sqlalchemy import text

    from app.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as s:
            await s.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database not reachable: {type(exc).__name__}")
    return AsyncSessionLocal
