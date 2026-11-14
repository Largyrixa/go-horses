"""Go Horses - API de leilão online (FastAPI + Prisma + PostgreSQL).

Rodar local:
    uvicorn app.main:app --reload --port 8088
Documentação interativa: http://localhost:8088/docs
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .auction_service import sync_auctions
from .config import (
    CORS_ORIGINS,
    DATABASE_URL,
    STATIC_DIR,
    SYNC_INTERVAL_SECONDS,
    UPLOAD_DIR,
)
from .db import db
from .errors import install_error_handlers
from .realtime import rooms
from .routers import auctions, auth, me, uploads

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("gohorses.main")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL não configurada. Copie backend/.env.example para backend/.env."
        )
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    await db.connect()
    log.info("Conectado ao Postgres via Prisma.")

    stop = asyncio.Event()

    async def ticker() -> None:
        while not stop.is_set():
            try:
                await sync_auctions(db, on_change=rooms.broadcast_state)
            except Exception:
                log.exception("Falha no processo de abertura/fechamento de leilões")
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=max(0.2, SYNC_INTERVAL_SECONDS)
                )
            except asyncio.TimeoutError:
                pass

    task = asyncio.create_task(ticker())
    try:
        yield
    finally:
        stop.set()
        await task
        await db.disconnect()
        log.info("Desconectado do banco.")


app = FastAPI(
    title="Go Horses - Leilão Online",
    version="1.0.0",
    description=(
        "API do leilão em tempo real. Dinheiro em centavos inteiros, "
        "horários em UTC, autenticação Bearer."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Date"],
)

install_error_handlers(app)

app.include_router(auth.router, prefix="/api")
app.include_router(auctions.router, prefix="/api")
app.include_router(me.router, prefix="/api")
app.include_router(uploads.router, prefix="/api")

# Fotos enviadas pelo próprio sistema e imagens de demonstração do seed.
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR), check_dir=False), name="uploads")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR), check_dir=False), name="static")


@app.get("/", tags=["health"])
async def root():
    return {"status": "ok", "service": "go-horses-api"}


@app.get("/health", tags=["health"])
@app.get("/api/health", tags=["health"])
async def health():
    await db.query_raw("SELECT 1")
    return {"status": "ok", "service": "go-horses-api"}
