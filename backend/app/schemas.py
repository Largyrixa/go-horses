"""Modelos de entrada da API (snake_case, igual ao contrato do frontend)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=60)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    # Bônus (RF29/RF31). O frontend atual não envia; fica 0 por padrão.
    monthly_income_cents: int | None = Field(default=None, ge=0)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class AuctionCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    category: str = Field(min_length=1, max_length=60)
    photos: list[str] = Field(min_length=3, max_length=10)
    starting_price: int = Field(gt=0, description="Centavos inteiros")
    starts_at: datetime
    duration_seconds: int = Field(ge=60, le=7 * 24 * 60 * 60)


class BidIn(BaseModel):
    amount: int = Field(gt=0, description="Centavos inteiros")


class AuctionUpdateIn(BaseModel):
    """RF23: só duração (antes do início) e fotos novas (sempre anexadas)."""

    duration_seconds: int | None = Field(default=None, ge=60, le=7 * 24 * 60 * 60)
    photos: list[str] | None = Field(default=None, min_length=1, max_length=10)


class PresignIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    size: int = Field(gt=0)
