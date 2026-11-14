"""Cadastro, login, sessão e perfil (RF01, RF02)."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Response
from prisma.errors import UniqueViolationError

from ..auction_service import credit_info
from ..config import SESSION_TTL_SECONDS
from ..db import db
from ..deps import get_current_session, get_current_user
from ..errors import ApiError
from ..schemas import LoginIn, RegisterIn
from ..security import (
    hash_password,
    hash_session_token,
    new_session_token,
    verify_password,
)
from ..serializers import ensure_utc, iso, user_dict, utcnow

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
async def register(payload: RegisterIn):
    email = str(payload.email).strip().lower()
    display_name = payload.display_name.strip()
    if not display_name:
        raise ApiError(422, "invalid_name", "Informe um nome de exibição.")

    existing = await db.user.find_unique(where={"email": email})
    if existing is not None:
        raise ApiError(409, "email_taken", "Já existe uma conta com esse e-mail.")

    try:
        user = await db.user.create(
            data={
                "email": email,
                "password_hash": hash_password(payload.password),
                "display_name": display_name,
                "monthly_income_cents": payload.monthly_income_cents or 0,
            }
        )
    except UniqueViolationError:
        raise ApiError(409, "email_taken", "Já existe uma conta com esse e-mail.")

    return user_dict(user)


@router.post("/login")
async def login(payload: LoginIn):
    email = str(payload.email).strip().lower()
    user = await db.user.find_unique(where={"email": email})
    if user is None or not verify_password(payload.password, user.password_hash):
        raise ApiError(401, "invalid_credentials", "E-mail ou senha incorretos.")

    token = new_session_token()
    expires_at = utcnow() + timedelta(seconds=SESSION_TTL_SECONDS)
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
    await db.session.delete(where={"id": session.id})
    return Response(status_code=204)


@router.get("/me")
async def me(user=Depends(get_current_user)):
    stats = await credit_info(db, user)
    return {**user_dict(user), **stats}
