"""Cadastro, login, sessão e perfil (RF01, RF02)."""
from __future__ import annotations

import asyncio
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from prisma.errors import UniqueViolationError

from ..auction_service import credit_info
from ..config import SESSION_TTL_SECONDS
from ..db import db
from ..deps import get_current_session, get_current_user
from ..errors import ApiError
from ..ratelimit import login_failures
from ..schemas import LoginIn, RegisterIn
from ..security import (
    hash_password,
    hash_session_token,
    new_session_token,
    verify_dummy_password,
    verify_password,
)
from ..serializers import iso, user_dict, utcnow

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
async def register(payload: RegisterIn):
    email = str(payload.email).strip().lower()
    # Normaliza espaços e remove caracteres de controle/invisíveis do nome.
    display_name = " ".join(
        "".join(ch for ch in payload.display_name if ch.isprintable() or ch.isspace()).split()
    )
    if not display_name:
        raise ApiError(422, "invalid_name", "Informe um nome de exibição.")

    existing = await db.user.find_unique(where={"email": email})
    if existing is not None:
        raise ApiError(409, "email_taken", "Já existe uma conta com esse e-mail.")

    try:
        user = await db.user.create(
            data={
                "email": email,
                # scrypt é pesado de propósito: roda fora do event loop para
                # não travar os lances e a sala enquanto calcula.
                "password_hash": await asyncio.to_thread(
                    hash_password, payload.password
                ),
                "display_name": display_name,
                "monthly_income_cents": payload.monthly_income_cents or 0,
            }
        )
    except UniqueViolationError:
        raise ApiError(409, "email_taken", "Já existe uma conta com esse e-mail.")

    return user_dict(user)


@router.post("/login")
async def login(payload: LoginIn, request: Request):
    email = str(payload.email).strip().lower()
    client_ip = request.client.host if request.client else "desconhecido"
    attempt_key = (client_ip, email)

    wait = login_failures.retry_after(attempt_key)
    if wait:
        raise ApiError(
            429,
            "too_many_attempts",
            "Muitas tentativas de login. Espere alguns minutos e tente de novo.",
            extra={"retry_after": wait},
        )

    user = await db.user.find_unique(where={"email": email})
    if user is None:
        await asyncio.to_thread(verify_dummy_password, payload.password)
        valid = False
    else:
        valid = await asyncio.to_thread(
            verify_password, payload.password, user.password_hash
        )
    if user is None or not valid:
        login_failures.record_failure(attempt_key)
        raise ApiError(401, "invalid_credentials", "E-mail ou senha incorretos.")
    login_failures.reset(attempt_key)

    now = utcnow()
    # Limpa as sessões vencidas desta conta (antes só saíam ao serem usadas).
    await db.session.delete_many(
        where={"user_id": user.id, "expires_at": {"lte": now}}
    )

    token = new_session_token()
    expires_at = now + timedelta(seconds=SESSION_TTL_SECONDS)
    await db.session.create(
        data={
            "token_hash": hash_session_token(token),
            "user": {"connect": {"id": user.id}},
            "expires_at": expires_at,
        }
    )
    return {"token": token, "user": user_dict(user), "expires_at": iso(expires_at)}


@router.post("/logout", status_code=204)
async def logout(session=Depends(get_current_session)):
    # delete_many: dois logouts simultâneos não viram erro 500.
    await db.session.delete_many(where={"id": session.id})
    return Response(status_code=204)


@router.get("/me")
async def me(user=Depends(get_current_user)):
    stats = await credit_info(db, user)
    return {**user_dict(user), **stats}
