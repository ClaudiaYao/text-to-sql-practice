"""
Vertex AI text-embedding-004 wrapper.

Uses task-type-aware embedding:
  RETRIEVAL_DOCUMENT — for schema chunks and few-shot examples stored in ChromaDB
  RETRIEVAL_QUERY    — for the user's question at retrieval time

Both functions run the synchronous Vertex AI SDK in a thread executor
so they don't block the async event loop.
"""
import asyncio
import logging

import vertexai  # type: ignore[import]
from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel  # type: ignore[import]

from app.config import settings

logger = logging.getLogger(__name__)

_TASK_DOCUMENT = "RETRIEVAL_DOCUMENT"
_TASK_QUERY = "RETRIEVAL_QUERY"


def _get_model() -> TextEmbeddingModel:
    vertexai.init(project=settings.vertexai_project, location=settings.vertexai_location)
    return TextEmbeddingModel.from_pretrained(settings.vertexai_embedding_model)


def _embed_sync(texts: list[str], task_type: str) -> list[list[float]]:
    model = _get_model()
    inputs = [TextEmbeddingInput(text, task_type) for text in texts]
    results = model.get_embeddings(inputs)
    return [r.values for r in results]


async def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts for storage (RETRIEVAL_DOCUMENT task type)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _embed_sync, texts, _TASK_DOCUMENT)


async def embed_query(text: str) -> list[float]:
    """Embed a single query text for retrieval (RETRIEVAL_QUERY task type)."""
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, _embed_sync, [text], _TASK_QUERY)
    return results[0]
