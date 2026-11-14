"""Regras de negócio do leilão: ciclo de vida, lances, crédito e consultas."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Awaitable, Callable

from prisma import Prisma, models
from prisma.enums import AuctionStatus

from .config import (
    BID_RATE_LIMIT_MS,
    CATEGORIES,
    ENFORCE_CREDIT,
    EXTENSION_WINDOW_SECONDS,
    MAX_EXTENSION_SECONDS,
    PAGE_SIZE,
    RECENT_BIDS,
)
from .errors import ApiError
from .serializers import (
    auction_dict,
    ensure_utc,
    min_bid_cents,
    room_state,
    status_value,
    utcnow,
)

log = logging.getLogger("gohorses.auctions")

AUCTION_INCLUDE = {
    "item": True,
    "seller": True,
    "leader": True,
    "winner": True,
}

FINAL_STATUSES = {AuctionStatus.sold, AuctionStatus.unsold, AuctionStatus.cancelled}
ALL_STATUSES = {status.value for status in AuctionStatus}


async def sync_auctions(
    db: Prisma,
    on_change: Callable[[str], Awaitable[None]] | None = None,
) -> None:
    """Abre e fecha leilões de acordo com o relógio do servidor (RF16-RF18).

    É seguro rodar várias vezes/em paralelo: as transições usam UPDATE condicional.
    """
    now = utcnow()
    changed: list[str] = []

    starting = await db.auction.find_many(
        where={"status": AuctionStatus.scheduled, "starts_at": {"lte": now}}
    )
    for auction in starting:
        updated = await db.auction.update_many(
            where={"id": auction.id, "status": AuctionStatus.scheduled},
            data={"status": AuctionStatus.running},
        )
        if updated:
            changed.append(auction.id)

    closing = await db.auction.find_many(
        where={"status": AuctionStatus.running, "ends_at": {"lte": now}}
    )
    for auction in closing:
        sold = auction.bid_count > 0
        # UPDATE condicional atômico: grava status, vencedor e preço final numa
        # única operação. Se um lance prorrogou ends_at no meio do caminho, a
        # condição `ends_at <= now` não casa e nada é fechado.
        updated = await db.execute_raw(
            """
            UPDATE "auctions"
               SET status = $1::"AuctionStatus",
                   final_price_cents = $2::int,
                   winner_id = $3,
                   closed_at = $4::timestamptz
             WHERE id = $5
               AND status = $6::"AuctionStatus"
               AND ends_at <= $7::timestamptz
            """,
            AuctionStatus.sold if sold else AuctionStatus.unsold,
            auction.current_price_cents if sold else None,
            auction.leader_id if sold else None,
            now,
            auction.id,
            AuctionStatus.running,
            now,
        )
        if updated:
            changed.append(auction.id)

    if on_change:
        for auction_id in changed:
            try:
                await on_change(auction_id)
            except Exception:  # uma falha de socket não pode parar o fechamento
                log.exception("Falha ao notificar mudança do leilão %s", auction_id)


async def get_auction(db: Prisma, auction_id: str) -> models.Auction:
    auction = await db.auction.find_unique(
        where={"id": auction_id}, include=AUCTION_INCLUDE
    )
    if auction is None:
        raise ApiError(404, "auction_not_found", "Leilão não encontrado.")
    return auction


async def list_auctions(
    db: Prisma,
    *,
    q: str = "",
    category: str = "",
    status: str = "",
    page: int = 1,
) -> dict[str, Any]:
    await sync_auctions(db)
    page = max(1, page)
    where: dict[str, Any] = {}
    q = q.strip()
    category = category.strip()
    status = status.strip().lower()

    if q:
        where["item"] = {
            "is": {"name": {"contains": q, "mode": "insensitive"}}
        }
    if category:
        where["item"] = {
            **where.get("item", {}),
            "is": {
                **where.get("item", {}).get("is", {}),
                "category": {"equals": category},
            },
        }
    if status:
        if status not in ALL_STATUSES:
            raise ApiError(
                422,
                "invalid_status",
                f"Estado inválido: {status}.",
            )
        where["status"] = AuctionStatus(status)
    else:
        # Padrão da listagem: Agendados e Em andamento (RF20).
        where["OR"] = [
            {"status": AuctionStatus.scheduled},
            {"status": AuctionStatus.running},
        ]

    order: list[dict[str, str]]
    if status in {"sold", "unsold", "cancelled"}:
        order = [{"updated_at": "desc"}]
    else:
        order = [{"ends_at": "asc"}, {"created_at": "desc"}]

    rows = await db.auction.find_many(
        where=where,
        include=AUCTION_INCLUDE,
        order=order,
        take=PAGE_SIZE + 1,
        skip=(page - 1) * PAGE_SIZE,
    )
    has_more = len(rows) > PAGE_SIZE
    items = [auction_dict(auction) for auction in rows[:PAGE_SIZE]]
    return {
        "items": items,
        "has_more": has_more,
        "server_time": _now_iso(),
    }


async def create_auction(
    db: Prisma, user: models.User, payload: Any
) -> dict[str, Any]:
    name = payload.name.strip()
    description = payload.description.strip()
    category = payload.category.strip()
    photos = [str(photo).strip() for photo in payload.photos]

    if not name or not description:
        raise ApiError(422, "invalid_auction", "Nome e descrição são obrigatórios.")
    if category not in CATEGORIES:
        raise ApiError(
            422,
            "invalid_category",
            f"Categoria inválida. Use uma destas: {', '.join(CATEGORIES)}.",
        )
    if not (3 <= len(photos) <= 10):
        raise ApiError(422, "invalid_photos", "Envie entre 3 e 10 fotos.")
    for photo in photos:
        if not photo or len(photo) > 2048:
            raise ApiError(422, "invalid_photos", "URL de foto inválida.")
        if not photo.startswith(("http://", "https://", "/uploads/", "/static/")):
            raise ApiError(
                422, "invalid_photos", "As fotos precisam ser URLs válidas."
            )

    now = utcnow()
    starts_at = ensure_utc(payload.starts_at)
    if starts_at < now - timedelta(seconds=120):
        raise ApiError(
            422, "invalid_start", "O início não pode estar no passado."
        )
    if starts_at > now + timedelta(days=30):
        raise ApiError(
            422,
            "invalid_start",
            "O início deve ser no máximo 30 dias à frente.",
        )
    if starts_at < now:
        starts_at = now

    ends_at = starts_at + timedelta(seconds=payload.duration_seconds)
    status = AuctionStatus.running if starts_at <= now else AuctionStatus.scheduled

    async with db.tx() as tx:
        item = await tx.item.create(
            data={
                "name": name,
                "description": description,
                "category": category,
                "photos": photos,
                "seller": {"connect": {"id": user.id}},
            }
        )
        auction = await tx.auction.create(
            data={
                "item": {"connect": {"id": item.id}},
                "seller": {"connect": {"id": user.id}},
                "status": status,
                "starting_price_cents": payload.starting_price,
                "current_price_cents": payload.starting_price,
                "starts_at": starts_at,
                "ends_at": ends_at,
                "original_ends_at": ends_at,
            }
        )

    created = await get_auction(db, auction.id)
    return auction_dict(created)


async def cancel_auction(
    db: Prisma, user: models.User, auction_id: str
) -> dict[str, Any]:
    await sync_auctions(db)
    auction = await get_auction(db, auction_id)
    if auction.seller_id != user.id:
        raise ApiError(
            403, "not_seller", "Só o comitente pode cancelar este leilão."
        )
    status = status_value(auction)
    if status == "cancelled":
        raise ApiError(409, "already_cancelled", "Este leilão já foi cancelado.")
    if status not in {"scheduled", "running"}:
        raise ApiError(
            409,
            "not_cancellable",
            "Este leilão já foi encerrado e não pode ser cancelado.",
        )
    if status == "running" and auction.bid_count > 0:
        raise ApiError(
            409,
            "has_bids",
            "Leilões em andamento com lances não podem ser cancelados.",
        )

    await db.auction.update(
        where={"id": auction_id},
        data={"status": AuctionStatus.cancelled, "cancelled_at": utcnow()},
    )
    return auction_dict(await get_auction(db, auction_id))


async def room_payload(
    db: Prisma,
    auction_id: str,
    *,
    participants: int,
    spectators: int,
) -> dict[str, Any]:
    await sync_auctions(db)
    auction = await get_auction(db, auction_id)
    bids = await db.bid.find_many(
        where={"auction_id": auction_id},
        include={"bidder": True},
        order={"created_at": "desc"},
        take=RECENT_BIDS,
    )
    return room_state(
        auction, bids, participants=participants, spectators=spectators
    )


async def credit_info(db: Prisma, user: models.User) -> dict[str, int]:
    """RF29-RF32: pontuação e crédito (usados no bônus e exibidos em /auth/me)."""
    now = utcnow()
    won = await db.auction.find_many(
        where={"winner_id": user.id, "status": AuctionStatus.sold}
    )
    purchases = len(won)
    total_purchased = sum(int(a.final_price_cents or 0) for a in won)
    income = max(0, int(user.monthly_income_cents or 0))
    days = max(0, (now - ensure_utc(user.created_at)).days)

    score = int(
        50 * min(income / 1_000_000, 1)
        + 20 * min(days / 180, 1)
        + 15 * min(purchases / 10, 1)
        + 15 * min(total_purchased / 2_000_000, 1)
        + 0.5
    )
    score = max(0, min(100, score))
    limit = int(income * 6 * score / 100)
    leading = await db.auction.find_many(
        where={"leader_id": user.id, "status": AuctionStatus.running}
    )
    reserved = sum(int(a.current_price_cents) for a in leading)
    return {
        "score": score,
        "monthly_income_cents": income,
        "purchases_count": purchases,
        "total_purchased_cents": total_purchased,
        "credit_limit_cents": limit,
        "credit_reserved_cents": reserved,
        "credit_available_cents": max(0, limit - reserved),
    }


async def place_bid(
    db: Prisma,
    user: models.User,
    auction_id: str,
    amount: int,
    idempotency_key: str,
) -> tuple[models.Bid, models.Auction, bool]:
    """Grava um lance com lock de linha (RF10-RF14).

    Retorna (bid, auction, replay). O lock `FOR UPDATE` serializa lances
    simultâneos do mesmo leilão no Postgres.
    """
    now = utcnow()
    bid_id: str | None = None
    replay = False

    async with db.tx(timeout=timedelta(seconds=10)) as tx:
        locked = await tx.query_raw(
            'SELECT id FROM "auctions" WHERE id = $1 FOR UPDATE', auction_id
        )
        if not locked:
            raise ApiError(404, "auction_not_found", "Leilão não encontrado.")

        auction = await tx.auction.find_unique(
            where={"id": auction_id}, include=AUCTION_INCLUDE
        )
        if auction is None:
            raise ApiError(404, "auction_not_found", "Leilão não encontrado.")

        # RF12: reenviar a mesma chave devolve o resultado original, antes de
        # qualquer outra validação (o leilão pode ter encerrado nesse meio-tempo).
        existing = await tx.bid.find_first(
            where={
                "auction_id": auction_id,
                "idempotency_key": idempotency_key,
            },
            include={"bidder": True},
        )
        if existing is not None:
            bid_id = existing.id
            replay = True
        else:
            status = auction.status
            starts_at = ensure_utc(auction.starts_at)
            ends_at = ensure_utc(auction.ends_at)

            if status == AuctionStatus.scheduled and now < starts_at:
                raise ApiError(
                    409,
                    "auction_not_started",
                    "O leilão ainda não começou.",
                )
            if status == AuctionStatus.scheduled and now >= starts_at:
                # Abre no ato, sem depender do tick de fundo.
                await tx.auction.update(
                    where={"id": auction_id},
                    data={"status": AuctionStatus.running},
                )
                status = AuctionStatus.running

            if status in FINAL_STATUSES or (status == AuctionStatus.running and now >= ends_at):
                raise ApiError(
                    409,
                    "auction_closed",
                    "O leilão já foi encerrado.",
                    min_bid=min_bid_cents(auction),
                )
            if status != AuctionStatus.running:
                raise ApiError(409, "auction_closed", "O leilão não está aberto.")

            if auction.seller_id == user.id:
                raise ApiError(
                    403,
                    "seller_cannot_bid",
                    "O comitente não pode dar lance no próprio leilão.",
                )
            if auction.leader_id == user.id:
                raise ApiError(
                    409,
                    "already_leading",
                    "Você já lidera este leilão; espere ser superado.",
                    min_bid=min_bid_cents(auction),
                )

            # RF13: no mínimo 500 ms entre lances do mesmo usuário.
            last = await tx.bid.find_first(
                where={
                    "auction_id": auction_id,
                    "bidder_id": user.id,
                },
                order={"created_at": "desc"},
            )
            if last is not None:
                elapsed_ms = (
                    now - ensure_utc(last.created_at)
                ).total_seconds() * 1000
                if elapsed_ms < BID_RATE_LIMIT_MS:
                    raise ApiError(
                        429,
                        "bid_too_fast",
                        "Espere um instante antes de enviar outro lance.",
                        min_bid=min_bid_cents(auction),
                    )

            minimum = min_bid_cents(auction)
            if amount < minimum:
                raise ApiError(
                    409,
                    "bid_too_low",
                    f"O lance mínimo agora é {minimum} centavos.",
                    min_bid=minimum,
                )

            if ENFORCE_CREDIT:
                w = await wallet_info(tx, user.id)
                if amount > w["available_cents"]:
                    raise ApiError(402, "insufficient_balance",
                        "Saldo insuficiente para este lance.",
                        extra={"available": w["available_cents"], "min_bid": minimum})

            # RF15: prorrogação de 2 min, limitada a 30 min acumulados.
            new_ends = ends_at
            extension = 0
            remaining = (ends_at - now).total_seconds()
            if remaining <= EXTENSION_WINDOW_SECONDS:
                desired = int(
                    max(
                        0,
                        (now + timedelta(seconds=EXTENSION_WINDOW_SECONDS) - ends_at).total_seconds(),
                    )
                )
                extension = min(
                    desired, MAX_EXTENSION_SECONDS - auction.extension_seconds
                )
                extension = max(0, extension)
                new_ends = ends_at + timedelta(seconds=extension)

            bid = await tx.bid.create(
                data={
                    "auction": {"connect": {"id": auction_id}},
                    "bidder": {"connect": {"id": user.id}},
                    "amount_cents": amount,
                    "idempotency_key": idempotency_key,
                }
            )
            await tx.auction.update(
                where={"id": auction_id},
                data={
                    "current_price_cents": amount,
                    "bid_count": {"increment": 1},
                    "leader": {"connect": {"id": user.id}},
                    "ends_at": new_ends,
                    "extension_seconds": auction.extension_seconds + extension,
                },
            )
            bid_id = bid.id

    assert bid_id is not None
    bid = await db.bid.find_unique(where={"id": bid_id}, include={"bidder": True})
    if bid is None:
        raise ApiError(500, "bid_missing", "Lance não encontrado após gravação.")
    auction = await get_auction(db, auction_id)
    return bid, auction, replay
async def wallet_info(db, user_id: str) -> dict[str, int]:
    user = await db.user.find_unique(where={"id": user_id})
    leading = await db.auction.find_many(
        where={"leader_id": user_id, "status": AuctionStatus.running}
    )
    reserved = sum(a.current_price_cents for a in leading)
    balance = user.balance_cents
    return {
        "balance_cents": balance,
        "reserved_cents": reserved,
        "available_cents": max(0, balance - reserved),
    }


async def deposit(db, user, amount: int) -> dict[str, int]:
    if not (100 <= amount <= 10_000_000):
        raise ApiError(422, "invalid_amount", "Valor de depósito inválido.")
    async with db.tx() as tx:
        await tx.user.update(
            where={"id": user.id}, data={"balance_cents": {"increment": amount}}
        )
        await tx.wallettransaction.create(
            data={"user": {"connect": {"id": user.id}}, "kind": "deposit", "amount_cents": amount}
        )
    return await wallet_info(db, user.id)


async def settle_sale(db, auction_id: str) -> None:
    a = await db.auction.find_unique(where={"id": auction_id})
    if not a or a.status != AuctionStatus.sold or not a.winner_id:
        return
    price = a.final_price_cents
    async with db.tx() as tx:
        await tx.user.update(where={"id": a.winner_id}, data={"balance_cents": {"decrement": price}})
        await tx.user.update(where={"id": a.seller_id}, data={"balance_cents": {"increment": price}})
        await tx.wallettransaction.create(data={"user": {"connect": {"id": a.winner_id}}, "kind": "purchase", "amount_cents": -price, "auction_id": a.id})
        await tx.wallettransaction.create(data={"user": {"connect": {"id": a.seller_id}}, "kind": "sale", "amount_cents": price, "auction_id": a.id})

def _now_iso() -> str:
    from .serializers import iso

    return iso(utcnow())
