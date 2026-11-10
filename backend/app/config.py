from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
# Resolve backend/.env relative to this file so it loads regardless of the working directory.
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    """All values come from backend/.env (or real environment variables). No defaults here."""

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    database_url: str

    # AWS Bedrock (credentials come from the standard AWS chain: env vars, ~/.aws, SSO, IAM role)
    aws_region: str
    aws_profile: str = ""  # optional; empty → default credential chain
    bedrock_model_id: str

    # Query execution
    query_timeout_ms: int
    max_rows: int

    # Accuracy
    max_attempts: int
    fewshot_top_k: int
    complex_candidates: int
    candidate_temperature: float

    # Cache
    cache_enabled: bool
    cache_max_entries: int
    sql_cache_ttl_seconds: int
    answer_cache_ttl_seconds: int
    schema_cache_ttl_seconds: int
    cache_persist_path: str = ""  # optional; empty → in-memory only

    # Chat history (SQLite file; relative paths resolve against backend/)
    history_db_path: str = ""  # optional; empty → data/history/history.sqlite3

    # API
    cors_origins: str  # comma-separated

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()  # type: ignore[call-arg]
