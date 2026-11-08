"""Audiyo API — FastAPI ilovasi."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import storage
from app.api import auth, billing, books, projects, voices
from app.config import get_settings
from app.db import async_engine
from app.services.billing import InsufficientCredits

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("audiyo")


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        storage.ensure_bucket()
    except Exception as exc:  # noqa: BLE001
        log.warning("S3 bucket tekshiruvi muvaffaqiyatsiz: %s", exc)
    yield
    await async_engine.dispose()


settings = get_settings()
app = FastAPI(title="Audiyo API", version="1.0.0", lifespan=lifespan,
              description="Oʻzbekcha AI video dublyaj va audiokitob platformasi")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(InsufficientCredits)
async def _insufficient(_: Request, exc: InsufficientCredits) -> JSONResponse:
    return JSONResponse(status_code=402, content={"detail": str(exc)})


API_PREFIX = "/api/v1"
for r in (auth.router, projects.router, books.router, voices.router, billing.router):
    app.include_router(r, prefix=API_PREFIX)


@app.get("/healthz", tags=["system"])
async def healthz() -> dict:
    async with async_engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok"}
