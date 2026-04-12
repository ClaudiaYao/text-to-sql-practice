from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.pipeline import PipelineError, run_pipeline
from app.database import get_db, get_schema_description
from app.models.schemas import QueryRequest, QueryResponse

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/api/query", response_model=QueryResponse)
async def query(request: QueryRequest, db: AsyncSession = Depends(get_db)):
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    try:
        result = await run_pipeline(question, db)
    except ValueError as exc:
        # LLM signalled the question cannot be answered with the schema
        raise HTTPException(status_code=422, detail=str(exc))
    except PipelineError as exc:
        # All retries exhausted
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Unexpected error: {exc}")

    return QueryResponse(
        sql=result.sql,
        columns=result.columns,
        rows=result.rows,
        row_count=result.row_count,
        execution_ms=result.execution_ms,
        attempts=result.attempts,
    )


@router.get("/api/schema")
async def schema(db: AsyncSession = Depends(get_db)):
    """Return the raw schema string — useful for debugging."""
    try:
        return {"schema": await get_schema_description(db)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))
