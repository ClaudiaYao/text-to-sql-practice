import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.schemas import ChatRequest, Conversation, ConversationSummary, QueryRequest, QueryResponse
from app.services import history as chat_store
from app.services.cache import cache_stats, clear_caches
from app.services.llm import LLMError, Unanswerable
from app.services.pipeline import PipelineError, PipelineResult, run_pipeline
from app.services.schema import get_schema_context

logger = logging.getLogger(__name__)
router = APIRouter()
MAX_HISTORY = 20  # messages of stored context handed to the follow-up rewriter


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
    """Chat turn, stored server-side. With `conversation_id` the server loads that conversation's history
    (so follow-ups like "now only for Canada" resolve); without it a new conversation is created.
    Failed turns are stored too; the error body then carries `conversation_id` as well as `detail`."""
    conv_id = request.conversation_id
    if conv_id is not None:
        if not await chat_store.conversation_exists(conv_id):
            raise HTTPException(status_code=404, detail="Conversation not found.")
        history = await chat_store.recent_messages(conv_id, MAX_HISTORY)
    else:
        history = [m.model_dump() for m in request.history]
    question = request.message.strip()
    try:
        response = await _run(question, db, history or None)
    except HTTPException as exc:
        if not question:  # nothing worth storing
            raise
        conv_id = await _save_safely(conv_id, question, "", None, str(exc.detail))
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "conversation_id": conv_id})
    response.conversation_id = await _save_safely(
        conv_id, question, response.answer, response.model_dump(exclude={"conversation_id"}), None
    )
    return response


async def _save_safely(conv_id, question, answer, result, error) -> str | None:
    """A history-store failure must never break answering the question."""
    try:
        return await chat_store.save_turn(conv_id, question, answer, result, error)
    except Exception:
        logger.exception("Could not store chat turn")
        return conv_id


@router.get("/api/conversations", response_model=list[ConversationSummary])
async def list_conversations():
    return await chat_store.list_conversations()


@router.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str):
    conv = await chat_store.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conv


@router.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    if not await chat_store.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"status": "deleted"}


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
