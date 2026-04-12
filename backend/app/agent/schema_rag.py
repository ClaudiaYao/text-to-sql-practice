"""
Schema RAG — stores one ChromaDB document per table and retrieves
the most relevant table descriptions for a given user question.

The schema string produced by database.get_schema_description() has one
table per line in the form:
    tablename(col1 TYPE, col2 TYPE, ...)

Each line becomes one document. At retrieval time the top-K most similar
table descriptions are returned as a single schema string, keeping the
LLM prompt lean and focused.
"""
import logging

import chromadb  # type: ignore[import]

from app.agent.embeddings import embed_documents, embed_query

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "sakila_schema"


class SchemaRAG:
    def __init__(self, chroma_client: chromadb.ClientAPI) -> None:
        self._collection = chroma_client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def is_populated(self) -> bool:
        return self._collection.count() > 0

    async def build(self, schema_description: str) -> None:
        """
        Parse the schema string into per-table chunks, embed them,
        and upsert into ChromaDB. Safe to call multiple times (upsert).
        """
        lines = [ln.strip() for ln in schema_description.splitlines() if ln.strip()]
        if not lines:
            logger.warning("[schema_rag] Empty schema — nothing to embed.")
            return

        table_names = [ln.split("(")[0].strip() for ln in lines]

        logger.info("[schema_rag] Embedding %d table descriptions…", len(lines))
        embeddings = await embed_documents(lines)

        self._collection.upsert(
            ids=table_names,
            documents=lines,
            embeddings=embeddings,
            metadatas=[{"table_name": name} for name in table_names],
        )
        logger.info("[schema_rag] Stored %d table embeddings.", len(lines))

    async def retrieve(self, question: str, top_k: int) -> str:
        """
        Return the top-K most relevant table descriptions as a schema string.
        Falls back to returning all documents if top_k >= total count.
        """
        count = self._collection.count()
        if count == 0:
            return ""

        k = min(top_k, count)
        query_embedding = await embed_query(question)

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            include=["documents"],
        )
        docs: list[str] = results["documents"][0]  # type: ignore[index]
        logger.info("[schema_rag] Retrieved %d / %d tables for query.", len(docs), count)
        return "\n".join(docs)
