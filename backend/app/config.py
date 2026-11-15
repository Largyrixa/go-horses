"""Configuração central do backend (carregada do .env)."""
from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
# Segredos de exemplo que estão no repositório público: nunca valem como chave.
_PLACEHOLDER_SECRETS = {
    "",
    "dev-secret-change-me",
    "troque-este-segredo-em-producao",
}
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
if SECRET_KEY in _PLACEHOLDER_SECRETS or len(SECRET_KEY) < 16:
    # Sem segredo próprio, qualquer pessoa que leia o repositório poderia
    # assinar links de upload. Usamos uma chave aleatória por processo: os
    # links duram 15 min e o serviço roda com um único worker.
    logging.getLogger("gohorses.config").warning(
        "SECRET_KEY ausente, curta ou igual ao valor de exemplo: usando uma chave "
        "aleatória por processo. Defina SECRET_KEY no backend/.env."
    )
    SECRET_KEY = secrets.token_urlsafe(48)
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "7"))
SYNC_INTERVAL_SECONDS = float(os.getenv("SYNC_INTERVAL_SECONDS", "0.5"))
ENFORCE_CREDIT = os.getenv("ENFORCE_CREDIT", "false").strip().lower() in {"1", "true", "yes", "on"}

# "*" não é aceito: a API usa credenciais e só deve responder a origens
# conhecidas. O front fala com a própria origem (proxy do Vite/Caddy).
CORS_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080"
    ).split(",")
    if origin.strip() and origin.strip() != "*"
]

# Base das URLs públicas de fotos. Vazio (recomendado) = URLs relativas
# ("/uploads/...", "/static/..."), que funcionam tanto no `npm run dev` (proxy
# do Vite) quanto em produção atrás do Caddy, sem depender de host/porta.
# Só preencha se as fotos forem servidas por OUTRA origem (ex.: S3/R2).
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")


def public_url(path: str) -> str:
    """Monta a URL pública de um asset; sem PUBLIC_BASE_URL, devolve o caminho."""
    return f"{PUBLIC_BASE_URL}{path}" if PUBLIC_BASE_URL else path


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
MAX_PAGE = 10_000
MAX_SEARCH_LENGTH = 120
# Teto de valores em centavos (R$ 10 milhões): as colunas são int32 no Postgres
# e o lance mínimo seguinte (preço + incremento) precisa caber nelas.
MAX_PRICE_CENTS = 1_000_000_000
MAX_IDEMPOTENCY_KEY_LENGTH = 200
# Força bruta no login: tentativas erradas por (IP, e-mail) dentro da janela.
LOGIN_MAX_FAILURES = 10
LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
# Sala: tempo para o cliente se autenticar depois de abrir o WebSocket.
WS_AUTH_TIMEOUT_SECONDS = 3
# Chat ao vivo da sala: tamanho máximo de mensagem e histórico em memória.
MAX_CHAT_LENGTH = 500
CHAT_HISTORY_LIMIT = 50
RECENT_BIDS = 20
SESSION_TTL_SECONDS = SESSION_TTL_DAYS * 24 * 60 * 60

# RF15: prorrogação de 2 minutos, no máximo 30 minutos acumulados.
EXTENSION_WINDOW_SECONDS = 120
MAX_EXTENSION_SECONDS = 1800
# RF13: no mínimo 500 ms entre lances do mesmo usuário no mesmo leilão.
BID_RATE_LIMIT_MS = 500
# RF12: idempotência
IDEMPOTENCY_HEADER = "Idempotency-Key"
