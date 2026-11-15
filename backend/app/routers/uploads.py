"""Upload de fotos sem serviço de nuvem configurado.

O contrato do frontend é: POST /api/uploads/presign devolve {upload_url, public_url};
o cliente faz PUT direto em upload_url. Aqui o "storage" é o disco local da VM,
servido em /uploads. Para trocar por S3/R2, basta mudar este arquivo.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response

from ..config import (
    SECRET_KEY,
    UPLOAD_DIR,
    UPLOAD_MAX_BYTES,
)
from ..config import public_url as make_public_url
from ..deps import get_current_user
from ..errors import ApiError
from ..schemas import PresignIn

router = APIRouter(prefix="/uploads", tags=["uploads"])

ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
TOKEN_TTL_SECONDS = 15 * 60
# Nome gerado pelo servidor: 32 hex + extensão permitida. Nada além disso é aceito.
KEY_PATTERN = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp)$")


def _matches_type(content_type: str, head: bytes) -> bool:
    """Confere a assinatura do arquivo: o Content-Type sozinho é só uma alegação."""
    if content_type == "image/jpeg":
        return head.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return False


def _signature(key: str, content_type: str, size: int, expires: int) -> str:
    message = f"{key}\n{content_type}\n{size}\n{expires}".encode("utf-8")
    return hmac.new(SECRET_KEY.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _make_token(key: str, content_type: str, size: int) -> str:
    expires = int(time.time()) + TOKEN_TTL_SECONDS
    payload = {
        "key": key,
        "content_type": content_type,
        "size": size,
        "expires": expires,
        "sig": _signature(key, content_type, size, expires),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _read_token(token: str) -> dict:
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("token malformado")
        key = str(payload["key"])
        content_type = str(payload["content_type"])
        size = int(payload["size"])
        expires = int(payload["expires"])
        signature = str(payload["sig"])
    except (KeyError, ValueError, TypeError):
        raise ApiError(403, "invalid_upload_token", "Link de upload inválido.")
    if expires < int(time.time()):
        raise ApiError(403, "expired_upload_token", "Link de upload expirado.")
    expected = _signature(key, content_type, size, expires)
    if not hmac.compare_digest(signature, expected):
        raise ApiError(403, "invalid_upload_token", "Link de upload inválido.")
    return {
        "key": key,
        "content_type": content_type,
        "size": size,
        "expires": expires,
    }


@router.post("/presign")
async def presign(payload: PresignIn, user=Depends(get_current_user)):
    content_type = payload.content_type.strip().lower()
    if content_type not in ALLOWED_TYPES:
        raise ApiError(
            422,
            "invalid_content_type",
            "Use uma imagem JPG, PNG ou WebP.",
        )
    if payload.size > UPLOAD_MAX_BYTES:
        raise ApiError(
            422,
            "file_too_large",
            f"A foto passa de {UPLOAD_MAX_BYTES // 1048576} MB.",
        )

    key = f"{secrets.token_hex(16)}{ALLOWED_TYPES[content_type]}"
    token = _make_token(key, content_type, payload.size)
    upload_url = make_public_url(f"/api/uploads/{key}?token={quote(token)}")
    public_url = make_public_url(f"/uploads/{key}")
    return {
        "upload_url": upload_url,
        "public_url": public_url,
        "content_type": content_type,
        "max_bytes": UPLOAD_MAX_BYTES,
    }


@router.put("/{key}", status_code=204)
async def upload(key: str, token: str, request: Request):
    payload = _read_token(token)
    if payload["key"] != key:
        raise ApiError(403, "invalid_upload_token", "Link de upload inválido.")

    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type != payload["content_type"] or content_type not in ALLOWED_TYPES:
        raise ApiError(
            415,
            "content_type_mismatch",
            "O tipo do arquivo não confere com o combinado.",
        )
    if not KEY_PATTERN.fullmatch(key) or not key.endswith(ALLOWED_TYPES[content_type]):
        raise ApiError(400, "invalid_key", "Nome de arquivo inválido.")

    limit = min(payload["size"], UPLOAD_MAX_BYTES)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise ApiError(413, "file_too_large", "Arquivo maior que o permitido.")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = (UPLOAD_DIR / key).resolve()
    if destination.parent != UPLOAD_DIR:
        raise ApiError(400, "invalid_key", "Nome de arquivo inválido.")
    if destination.exists():
        # O link vale para um único envio: não deixa trocar a foto de um
        # leilão já publicado reaproveitando o link dentro da validade.
        raise ApiError(409, "already_uploaded", "Esta foto já foi enviada.")

    # Lê em pedaços e para assim que passa do limite, em vez de carregar na
    # memória um corpo de tamanho arbitrário.
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > limit:
            raise ApiError(413, "file_too_large", "Arquivo maior que o permitido.")
        chunks.append(chunk)
    body = b"".join(chunks)
    if not body:
        raise ApiError(422, "empty_file", "Arquivo vazio.")
    if not _matches_type(content_type, body[:16]):
        raise ApiError(
            415,
            "invalid_image",
            "O arquivo não é uma imagem JPG, PNG ou WebP válida.",
        )

    # Grava num temporário e publica com link exclusivo: nunca fica arquivo
    # pela metade em /uploads e dois envios simultâneos não se sobrescrevem.
    temporary = destination.with_name(f".{key}.{secrets.token_hex(8)}.tmp")
    try:
        temporary.write_bytes(body)
        try:
            os.link(temporary, destination)
        except FileExistsError:
            raise ApiError(409, "already_uploaded", "Esta foto já foi enviada.")
    finally:
        temporary.unlink(missing_ok=True)
    return Response(status_code=204)
