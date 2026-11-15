"""Conversão dos modelos Prisma para o JSON que o frontend consome."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from prisma import models

from .config import RECENT_BIDS

# RF14: referência de incremento por faixa de preço (em centavos).
_BID_INCREMENTS = (
    (9_999, 100),
    (49_999, 500),
    (99_999, 1_000),
    (499_999, 5_000),
    (2_499_999, 10_000),
    (None, 50_000),
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return ensure_utc(value).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def format_brl(cents: int) -> str:
    """Formata centavos como moeda brasileira: 30500 -> 'R$ 305,00'."""
    reais = f"{cents / 100:,.2f}".translate(str.maketrans({",": "X", ".": ","}))
    return "R$ " + reais.replace("X", ".")


def bid_increment_cents(price_cents: int) -> int:
    for ceiling, increment in _BID_INCREMENTS:
        if ceiling is None or price_cents <= ceiling:
            return increment
    return 50_000


def min_bid_cents(auction: models.Auction) -> int:
    if auction.bid_count <= 0:
        return auction.starting_price_cents
    return auction.current_price_cents + bid_increment_cents(auction.current_price_cents)


def status_value(auction: models.Auction) -> str:
    return auction.status.value if hasattr(auction.status, "value") else str(auction.status)


def asset_path(url: str) -> str:
    """Converte fotos do próprio storage para caminho relativo.

    O front é sempre servido na mesma origem da API (Vite em dev, Caddy em
    produção), então `/uploads/...` e `/static/...` funcionam nos dois. Isso
    também conserta registros antigos que guardaram a origem absoluta
    (`PUBLIC_BASE_URL`), que quebrariam ao trocar de host/porta.
    """
    parts = urlsplit(url)
    if parts.netloc and parts.path.startswith(("/uploads/", "/static/")):
        return urlunsplit(("", "", parts.path, parts.query, ""))
    return url


def mask_name(name: str | None) -> str:
    """Primeiro nome + inicial do último (RF09), igual ao que o front exibe.

    O mascaramento é feito aqui, no servidor: as rotas de leilão são públicas
    e antes devolviam o nome completo de comitente, líder e vencedor.
    """
    parts = str(name or "").split()
    if not parts:
        return "—"
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[-1][0].upper()}."


def short_user(user: models.User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {"id": user.id, "display_name": mask_name(user.display_name)}


def user_dict(user: models.User, *, include_email: bool = True) -> dict[str, Any]:
    """`include_email=True` é a visão do próprio usuário (nome completo e e-mail).

    A visão pública (`include_email=False`) leva o nome mascarado.
    """
    data = {
        "id": user.id,
        "display_name": user.display_name if include_email else mask_name(user.display_name),
        "created_at": iso(user.created_at),
    }
    if include_email:
        data["email"] = user.email
    return data


def auction_dict(auction: models.Auction) -> dict[str, Any]:
    item = auction.item
    if item is None:
        raise RuntimeError("auction_dict exige item carregado (include)")
    seller = auction.seller
    if seller is None:
        raise RuntimeError("auction_dict exige seller carregado (include)")

    return {
        "id": auction.id,
        "name": item.name,
        "description": item.description,
        "category": item.category,
        "photos": [asset_path(p) for p in (item.photos or [])],
        "seller": short_user(seller),
        "status": status_value(auction),
        "starting_price": auction.starting_price_cents,
        "current_price": auction.current_price_cents,
        "min_bid": min_bid_cents(auction),
        "bid_count": auction.bid_count,
        "leader": short_user(auction.leader),
        "winner": short_user(auction.winner),
        "final_price": auction.final_price_cents,
        "starts_at": iso(auction.starts_at),
        "ends_at": iso(auction.ends_at),
        "created_at": iso(auction.created_at),
    }


def bid_dict(bid: models.Bid) -> dict[str, Any]:
    bidder = bid.bidder
    return {
        "id": bid.id,
        "auction_id": bid.auction_id,
        "amount": bid.amount_cents,
        "created_at": iso(bid.created_at),
        "bidder": short_user(bidder),
        "bidder_name": mask_name(bidder.display_name) if bidder else None,
    }


def room_state(
    auction: models.Auction,
    bids: list[models.Bid],
    *,
    participants: int,
    spectators: int,
) -> dict[str, Any]:
    return {
        "auction": auction_dict(auction),
        "recent_bids": [bid_dict(bid) for bid in bids[:RECENT_BIDS]],
        "participants": participants,
        "spectators": spectators,
        "server_time": iso(utcnow()),
    }
