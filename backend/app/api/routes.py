import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.schemas import ChatRequest, QueryRequest, QueryResponse
from app.services.cache import cache_stats, clear_caches
from app.services.llm import LLMError, Unanswerable
from app.services.pipeline import PipelineError, PipelineResult, run_pipeline
from app.services.schema import get_schema_context

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_response(r: PipelineResult) -> QueryResponse:
    return QueryResponse(
        answer=r.answer,
        sql=r.sql,
        columns=r.columns,
        rows=r.rows,
        row_count=r.row_count,
        truncated=r.truncated,
        execution_ms=r.execution_ms,
        attempts=r.attempts,
        cached=r.cached,
        complex=r.complex,
        candidates=r.candidates,
        agreement=r.agreement,
        standalone_question=r.standalone_question,
    )


async def _run(question: str, db: AsyncSession, history: list[dict] | None) -> QueryResponse:
    question = question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    try:
        return _to_response(await run_pipeline(question, db, history))
    except Unanswerable as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except PipelineError as exc:
        detail = str(exc) + (f"\n\nLast SQL:\n{exc.sql}" if exc.sql else "")
        raise HTTPException(status_code=400, detail=detail)
    except LLMError as exc:
        logger.exception("LLM failure")
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected pipeline failure")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {exc}")


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/api/query", response_model=QueryResponse)
async def query(request: QueryRequest, db: AsyncSession = Depends(get_db)):
    """Single question, no conversation context."""
    return await _run(request.question, db, None)


@router.post("/api/chat", response_model=QueryResponse)
async def chat(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Chat turn: `history` lets follow-ups like "now only for Canada" be resolved."""
    history = [m.model_dump() for m in request.history]
    return await _run(request.message, db, history or None)


@router.get("/api/schema")
async def schema(db: AsyncSession = Depends(get_db)):
    """The schema text the LLM sees — useful for debugging."""
    try:
        ctx = await get_schema_context(db)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"hash": ctx.hash, "schema": ctx.text}


@router.get("/api/cache/stats")
async def cache_statistics():
    return cache_stats()


@router.delete("/api/cache")
async def clear_cache():
    """Evict cached SQL/answers — use after a wrong answer was cached or after changing prompts."""
    clear_caches()
    return {"status": "cleared"}
