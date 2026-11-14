"""Configuração central do backend (carregada do .env)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "7"))
SYNC_INTERVAL_SECONDS = float(os.getenv("SYNC_INTERVAL_SECONDS", "0.5"))
ENFORCE_CREDIT = os.getenv("ENFORCE_CREDIT", "false").strip().lower() in {"1", "true", "yes", "on"}

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
_upload_dir = Path(os.getenv("UPLOAD_DIR", "uploads"))
if not _upload_dir.is_absolute():
    _upload_dir = BASE_DIR / _upload_dir
UPLOAD_DIR = _upload_dir.resolve()
UPLOAD_MAX_BYTES = int(os.getenv("UPLOAD_MAX_BYTES", str(5 * 1024 * 1024)))
STATIC_DIR = BASE_DIR / "static"

# Decisões da equipe (documento de requisitos, seção 8)
CATEGORIES = [
    "Eletrônicos",
    "Casa",
    "Moda",
    "Veículos",
    "Arte e colecionáveis",
    "Esportes",
    "Outros",
]
MIN_PHOTOS = 3
MAX_PHOTOS = 10
MIN_DURATION_SECONDS = 60
MAX_DURATION_SECONDS = 7 * 24 * 60 * 60
MAX_START_AHEAD_SECONDS = 30 * 24 * 60 * 60
START_TOLERANCE_SECONDS = 120
PAGE_SIZE = 12
RECENT_BIDS = 20
SESSION_TTL_SECONDS = SESSION_TTL_DAYS * 24 * 60 * 60

# RF15: prorrogação de 2 minutos, no máximo 30 minutos acumulados.
EXTENSION_WINDOW_SECONDS = 120
MAX_EXTENSION_SECONDS = 1800
# RF13: no mínimo 500 ms entre lances do mesmo usuário no mesmo leilão.
BID_RATE_LIMIT_MS = 500
# RF12: idempotência
IDEMPOTENCY_HEADER = "Idempotency-Key"
