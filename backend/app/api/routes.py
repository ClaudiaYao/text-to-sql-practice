import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.gemini import generate_sql
from app.database import execute_query, get_db, get_schema_description
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

    # 1. Get live schema from the database
    try:
        schema = await get_schema_description(db)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cannot reach database: {exc}")

    # 2. Ask the LLM to produce SQL
    try:
        sql = await generate_sql(question, schema)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM error: {exc}")

    # 3. Execute the generated SQL
    t0 = time.perf_counter()
    try:
        columns, rows = await execute_query(db, sql)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"SQL execution failed: {exc}\n\nGenerated SQL:\n{sql}",
        )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    return QueryResponse(
        sql=sql,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        execution_ms=round(elapsed_ms, 2),
    )


@router.get("/api/schema")
async def schema(db: AsyncSession = Depends(get_db)):
    """Return the raw schema string — useful for debugging."""
    try:
        return {"schema": await get_schema_description(db)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))
