"""Dependências de autenticação (Bearer token de sessão)."""
from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .db import db
from .errors import ApiError
from .security import hash_session_token
from .serializers import ensure_utc, utcnow

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(401, "unauthorized", "Entre para continuar.")
    token = credentials.credentials.strip()
    if not token:
        raise ApiError(401, "unauthorized", "Entre para continuar.")

    session = await db.session.find_unique(
        where={"token_hash": hash_session_token(token)},
        include={"user": True},
    )
    if session is None:
        raise ApiError(401, "unauthorized", "Sessão inválida. Entre novamente.")
    if ensure_utc(session.expires_at) <= utcnow():
        await db.session.delete(where={"id": session.id})
        raise ApiError(401, "session_expired", "Sua sessão expirou. Entre novamente.")
    if session.user is None:
        raise ApiError(401, "unauthorized", "Sessão inválida. Entre novamente.")
    return session


async def get_current_user(session=Depends(get_current_session)):
    return session.user
