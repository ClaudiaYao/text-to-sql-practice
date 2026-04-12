"""
RAG singleton context — initialised once at app startup, reused per request.

Exposes:
  init_rag(db_session)  — called from FastAPI lifespan; embeds schema + examples
  get_rag_context(question, db_session)
                        — called by the pipeline; returns (schema_str, fewshot_examples)
                          falls back to full schema if RAG is disabled or unavailable
"""
import logging

import chromadb  # type: ignore[import]
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.fewshot_rag import FewShotRAG
from app.agent.schema_rag import SchemaRAG
from app.config import settings
from app.database import get_schema_description

logger = logging.getLogger(__name__)

# Module-level singletons — set once during startup, read-only afterwards
_schema_rag: SchemaRAG | None = None
_fewshot_rag: FewShotRAG | None = None


async def init_rag(db: AsyncSession) -> None:
    """
    Initialise ChromaDB collections and embed schema + few-shot examples.
    Already-populated collections are skipped (embeddings persist on disk).
    Errors are logged but never raised — the app always starts cleanly.
    """
    global _schema_rag, _fewshot_rag

    if not settings.rag_enabled:
        logger.info("[rag] RAG_ENABLED=false — skipping initialisation.")
        return

    if not settings.vertexai_project:
        logger.warning(
            "[rag] VERTEXAI_PROJECT is not set — RAG disabled. "
            "Set it in .env and restart to enable RAG."
        )
        return

    try:
        client = chromadb.PersistentClient(path=settings.chroma_persist_path)

        # ── Schema RAG ────────────────────────────────────────────────────
        _schema_rag = SchemaRAG(client)
        if _schema_rag.is_populated:
            logger.info("[rag] Schema collection already populated — skipping re-embed.")
        else:
            schema_description = await get_schema_description(db)
            await _schema_rag.build(schema_description)

        # ── Few-shot RAG ──────────────────────────────────────────────────
        _fewshot_rag = FewShotRAG(client)
        if _fewshot_rag.is_populated:
            logger.info("[rag] Few-shot collection already populated — skipping re-embed.")
        else:
            await _fewshot_rag.build()

        logger.info("[rag] Initialisation complete.")

    except Exception:
        logger.exception("[rag] Initialisation failed — falling back to full-schema mode.")
        _schema_rag = None
        _fewshot_rag = None


async def get_rag_context(
    question: str,
    db: AsyncSession,
) -> tuple[str, list[dict]]:
    """
    Retrieve relevant schema chunks and few-shot examples for the question.

    Returns:
        schema_str      — retrieved table descriptions (or full schema as fallback)
        fewshot_examples — list of {"question": ..., "sql": ...} dicts
    """
    # Fallback: full schema, no examples
    if _schema_rag is None or _fewshot_rag is None:
        logger.debug("[rag] RAG not initialised — using full schema fallback.")
        schema_str = await get_schema_description(db)
        return schema_str, []

    schema_str = await _schema_rag.retrieve(question, top_k=settings.rag_schema_top_k)
    fewshot_examples = await _fewshot_rag.retrieve(question, top_k=settings.rag_fewshot_top_k)

    # Safety: if retrieval returned nothing, fall back to full schema
    if not schema_str:
        logger.warning("[rag] Schema retrieval returned empty — falling back to full schema.")
        schema_str = await get_schema_description(db)

    return schema_str, fewshot_examples
