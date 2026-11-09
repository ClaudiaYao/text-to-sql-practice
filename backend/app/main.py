import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings
from app.database import AsyncSessionLocal
from app.services.examples import load_examples
from app.services.schema import get_schema_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm the schema cache and example bank so the first user request is fast."""
    logger.info("Loaded %d curated examples", len(load_examples()))
    try:
        async with AsyncSessionLocal() as session:
            ctx = await get_schema_context(session)
        logger.info("Schema ready (hash %s)", ctx.hash)
    except Exception:
        logger.exception("Could not introspect the schema at startup — will retry on first request")
    yield


app = FastAPI(title="Text-to-SQL API", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
