import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.database import AsyncSessionLocal
from app.agent.rag_context import init_rag

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise RAG vector stores once at startup; clean up on shutdown."""
    logger.info("Starting up — initialising RAG…")
    async with AsyncSessionLocal() as session:
        await init_rag(session)
    logger.info("RAG initialisation complete. Server is ready.")
    yield
    logger.info("Shutting down.")


app = FastAPI(title="Text-to-SQL API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
