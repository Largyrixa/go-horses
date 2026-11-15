"""Modelos de entrada da API (snake_case, igual ao contrato do frontend)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from .config import (
    MAX_DURATION_SECONDS,
    MAX_PHOTOS,
    MAX_PRICE_CENTS,
    MIN_DURATION_SECONDS,
    MIN_PHOTOS,
)


class RegisterIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=60)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    # Bônus (RF29/RF31). O frontend atual não envia; fica 0 por padrão.
    monthly_income_cents: int | None = Field(
        default=None, ge=0, le=MAX_PRICE_CENTS, strict=True
    )


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class AuctionCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    category: str = Field(min_length=1, max_length=60)
    photos: list[str] = Field(min_length=MIN_PHOTOS, max_length=MAX_PHOTOS)
    # strict: só inteiro JSON (nada de true/"100"/100.0); o teto evita estouro
    # das colunas int32 do banco, que viraria erro 500.
    starting_price: int = Field(
        gt=0, le=MAX_PRICE_CENTS, strict=True, description="Centavos inteiros"
    )
    starts_at: datetime
    duration_seconds: int = Field(
        ge=MIN_DURATION_SECONDS, le=MAX_DURATION_SECONDS, strict=True
    )


class BidIn(BaseModel):
    amount: int = Field(
        gt=0, le=MAX_PRICE_CENTS, strict=True, description="Centavos inteiros"
    )


class AuctionUpdateIn(BaseModel):
    """RF23: só duração (antes do início) e fotos novas (sempre anexadas)."""

    duration_seconds: int | None = Field(
        default=None,
        ge=MIN_DURATION_SECONDS,
        le=MAX_DURATION_SECONDS,
        strict=True,
    )
    photos: list[str] | None = Field(
        default=None, min_length=1, max_length=MAX_PHOTOS
    )


class PresignIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    size: int = Field(gt=0, strict=True)
