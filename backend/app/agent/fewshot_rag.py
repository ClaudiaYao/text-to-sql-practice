"""
Few-shot RAG — stores curated (question, SQL) pairs in ChromaDB and
retrieves the most similar examples for a given user question.

Examples are loaded from data/seed/sakila_examples.json at startup.
The question text is embedded (not the SQL); SQL is stored as metadata.
At retrieval time the top-K most similar examples are returned and
injected into the LLM generation prompt.
"""
import json
import logging
from pathlib import Path

import chromadb  # type: ignore[import]

from app.agent.embeddings import embed_documents, embed_query

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "sakila_fewshot"
_SEED_FILE = Path("data/seed/sakila_examples.json")


class FewShotRAG:
    def __init__(self, chroma_client: chromadb.ClientAPI) -> None:
        self._collection = chroma_client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def is_populated(self) -> bool:
        return self._collection.count() > 0

    async def build(self) -> None:
        """
        Load examples from the seed file, embed the question texts,
        and upsert into ChromaDB. Safe to call multiple times (upsert).
        """
        if not _SEED_FILE.exists():
            logger.warning("[fewshot_rag] Seed file not found: %s", _SEED_FILE)
            return

        examples: list[dict] = json.loads(_SEED_FILE.read_text(encoding="utf-8"))
        if not examples:
            return

        questions = [ex["question"] for ex in examples]
        ids = [f"example_{i}" for i in range(len(examples))]

        logger.info("[fewshot_rag] Embedding %d few-shot examples…", len(questions))
        embeddings = await embed_documents(questions)

        self._collection.upsert(
            ids=ids,
            documents=questions,
            embeddings=embeddings,
            metadatas=[{"question": ex["question"], "sql": ex["sql"]} for ex in examples],
        )
        logger.info("[fewshot_rag] Stored %d few-shot embeddings.", len(questions))

    async def retrieve(self, question: str, top_k: int) -> list[dict]:
        """
        Return the top-K most similar (question, sql) pairs as a list of dicts.
        Returns an empty list if collection is empty.
        """
        count = self._collection.count()
        if count == 0:
            return []

        k = min(top_k, count)
        query_embedding = await embed_query(question)

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            include=["metadatas"],
        )
        metadatas: list[dict] = results["metadatas"][0]  # type: ignore[index]
        logger.info("[fewshot_rag] Retrieved %d few-shot examples.", len(metadatas))
        return [{"question": m["question"], "sql": m["sql"]} for m in metadatas]
