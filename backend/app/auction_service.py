"""Regras de negócio do leilão: ciclo de vida, lances, crédito e consultas."""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any, Awaitable, Callable

from prisma import Prisma, models
from prisma.enums import AuctionStatus

from .config import (
    BID_RATE_LIMIT_MS,
    CATEGORIES,
    ENFORCE_CREDIT,
    EXTENSION_WINDOW_SECONDS,
    MAX_DURATION_SECONDS,
    MAX_EXTENSION_SECONDS,
    MAX_PAGE,
    MAX_PHOTOS,
    MAX_PRICE_CENTS,
    MAX_SEARCH_LENGTH,
    MAX_START_AHEAD_SECONDS,
    MIN_DURATION_SECONDS,
    MIN_PHOTOS,
    PAGE_SIZE,
    PUBLIC_BASE_URL,
    RECENT_BIDS,
    START_TOLERANCE_SECONDS,
    STATIC_DIR,
    UPLOAD_DIR,
)
from .errors import ApiError
from .serializers import (
    asset_path,
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

# Fotos aceitas num leilão: só arquivos do próprio storage. URL externa
# permitiria rastrear quem abre o anúncio e apontar para conteúdo arbitrário.
_UPLOAD_PHOTO = re.compile(r"^/uploads/([0-9a-f]{32}\.(?:jpg|png|webp))$")
_STATIC_PHOTO = re.compile(
    r"^/static/((?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.(?:svg|png|jpg|jpeg|webp))$"
)


def _escape_like(term: str) -> str:
    """Escapa os curingas do LIKE: `%`, `_` e a barra invertida são texto comum."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _normalize_photo(raw: str) -> str:
    """Valida uma foto e devolve o caminho relativo guardado no banco."""
    photo = str(raw).strip()
    if PUBLIC_BASE_URL and photo.startswith(PUBLIC_BASE_URL + "/"):
        photo = asset_path(photo)
    upload = _UPLOAD_PHOTO.fullmatch(photo)
    if upload:
        if not (UPLOAD_DIR / upload.group(1)).is_file():
            raise ApiError(
                422, "invalid_photos", "Uma das fotos não foi enviada. Envie de novo."
            )
        return photo
    static = _STATIC_PHOTO.fullmatch(photo)
    if static and (STATIC_DIR / static.group(1)).is_file():
        return photo
    raise ApiError(
        422,
        "invalid_photos",
        "As fotos precisam ser enviadas pelo próprio site (JPG, PNG ou WebP).",
    )


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
        # UPDATE condicional atômico: status, vencedor e preço final saem das
        # colunas da PRÓPRIA linha no instante do UPDATE, não da leitura feita
        # acima. Assim um lance aceito entre a leitura e o fechamento não é
        # perdido (vencedor/preço antigos). Se o lance prorrogou ends_at, a
        # condição `ends_at <= now` não casa e nada é fechado.
        updated = await db.execute_raw(
            """
            UPDATE "auctions"
               SET status = CASE WHEN bid_count > 0
                                 THEN $1::"AuctionStatus"
                                 ELSE $2::"AuctionStatus" END,
                   final_price_cents = CASE WHEN bid_count > 0
                                            THEN current_price_cents END,
                   winner_id = CASE WHEN bid_count > 0 THEN leader_id END,
                   closed_at = $3::timestamptz,
                   updated_at = $3::timestamptz
             WHERE id = $4
               AND status = $5::"AuctionStatus"
               AND ends_at <= $6::timestamptz
            """,
            AuctionStatus.sold,
            AuctionStatus.unsold,
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
    page = min(max(1, page), MAX_PAGE)
    where: dict[str, Any] = {}
    q = q.strip()[:MAX_SEARCH_LENGTH]
    category = category.strip()
    status = status.strip().lower()

    if q:
        where["item"] = {
            "is": {"name": {"contains": _escape_like(q), "mode": "insensitive"}}
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
                "Estado inválido.",
            )
        where["status"] = AuctionStatus(status)
    else:
        # Padrão da listagem: Agendados e Em andamento (RF20).
        where["OR"] = [
            {"status": AuctionStatus.scheduled},
            {"status": AuctionStatus.running},
        ]

    # O `id` no fim desempata registros com a mesma data: sem ele a paginação
    # podia repetir ou pular leilões entre uma página e outra.
    order: list[dict[str, str]]
    if status in {"sold", "unsold", "cancelled"}:
        order = [{"updated_at": "desc"}, {"id": "asc"}]
    else:
        order = [{"ends_at": "asc"}, {"created_at": "desc"}, {"id": "asc"}]

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


def _clean_photos(photos: list[str]) -> list[str]:
    """Valida e deduplica fotos do próprio storage (RF05/RF23/RF28)."""
    return list(dict.fromkeys(_normalize_photo(photo) for photo in photos))


def _auction_fields(payload: Any) -> dict[str, Any]:
    """Valida o payload de criação/relistagem (RF05/RF28)."""
    name = " ".join(payload.name.split())
    description = payload.description.strip()
    category = payload.category.strip()
    photos = _clean_photos(payload.photos)

    if not name or not description:
        raise ApiError(422, "invalid_auction", "Nome e descrição são obrigatórios.")
    if category not in CATEGORIES:
        raise ApiError(
            422,
            "invalid_category",
            f"Categoria inválida. Use uma destas: {', '.join(CATEGORIES)}.",
        )
    if not (MIN_PHOTOS <= len(photos) <= MAX_PHOTOS):
        raise ApiError(
            422,
            "invalid_photos",
            f"Envie entre {MIN_PHOTOS} e {MAX_PHOTOS} fotos diferentes.",
        )
    if not (0 < payload.starting_price <= MAX_PRICE_CENTS):
        raise ApiError(422, "invalid_price", "Preço inicial inválido.")
    if not (MIN_DURATION_SECONDS <= payload.duration_seconds <= MAX_DURATION_SECONDS):
        raise ApiError(
            422, "invalid_duration", "A duração deve ficar entre 1 minuto e 7 dias."
        )

    now = utcnow()
    starts_at = ensure_utc(payload.starts_at)
    if starts_at < now - timedelta(seconds=START_TOLERANCE_SECONDS):
        raise ApiError(
            422, "invalid_start", "O início não pode estar no passado."
        )
    if starts_at > now + timedelta(seconds=MAX_START_AHEAD_SECONDS):
        raise ApiError(
            422,
            "invalid_start",
            f"O início deve ser no máximo {MAX_START_AHEAD_SECONDS // 86400} dias à frente.",
        )
    if starts_at < now:
        starts_at = now

    return {
        "name": name,
        "description": description,
        "category": category,
        "photos": photos,
        "starts_at": starts_at,
        "ends_at": starts_at + timedelta(seconds=payload.duration_seconds),
        "status": (
            AuctionStatus.running if starts_at <= now else AuctionStatus.scheduled
        ),
    }


async def create_auction(
    db: Prisma, user: models.User, payload: Any
) -> dict[str, Any]:
    fields = _auction_fields(payload)

    async with db.tx() as tx:
        item = await tx.item.create(
            data={
                "name": fields["name"],
                "description": fields["description"],
                "category": fields["category"],
                "photos": fields["photos"],
                "seller": {"connect": {"id": user.id}},
            }
        )
        auction = await tx.auction.create(
            data={
                "item": {"connect": {"id": item.id}},
                "seller": {"connect": {"id": user.id}},
                "status": fields["status"],
                "starting_price_cents": payload.starting_price,
                "current_price_cents": payload.starting_price,
                "starts_at": fields["starts_at"],
                "ends_at": fields["ends_at"],
                "original_ends_at": fields["ends_at"],
            }
        )

    created = await get_auction(db, auction.id)
    return auction_dict(created)


async def update_auction(
    db: Prisma, user: models.User, auction_id: str, payload: Any
) -> dict[str, Any]:
    """RF23: o comitente altera a duração (antes do início) e acrescenta fotos.

    Nada pode ser removido ou trocado: o payload só carrega fotos novas, que são
    anexadas ao item. A duração trava quando o leilão abre, para não mover a
    linha de chegada de quem já está dando lances.
    """
    async with db.tx() as tx:
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
        if auction.seller_id != user.id:
            raise ApiError(
                403, "not_seller", "Só o comitente pode editar este leilão."
            )

        status = status_value(auction)
        if status not in {"scheduled", "running"}:
            raise ApiError(
                409,
                "not_editable",
                "Este leilão já foi encerrado e não pode ser editado.",
            )

        changes: dict[str, Any] = {}
        if payload.duration_seconds is not None:
            if status != "scheduled":
                raise ApiError(
                    409,
                    "duration_locked",
                    "A duração só pode ser alterada antes do início.",
                )
            starts_at = ensure_utc(auction.starts_at)
            ends_at = starts_at + timedelta(seconds=payload.duration_seconds)
            changes.update(
                {
                    "ends_at": ends_at,
                    "original_ends_at": ends_at,
                    "extension_seconds": 0,
                }
            )

        added: list[str] = []
        if payload.photos:
            # Trava o item antes de ler as fotos: duas edições concorrentes não
            # podem sobrescrever o acréscimo uma da outra.
            await tx.query_raw(
                'SELECT id FROM "items" WHERE id = $1 FOR UPDATE', auction.item_id
            )
            item = await tx.item.find_unique(where={"id": auction.item_id})
            existing = list((item.photos if item else auction.item.photos) or [])
            for photo in _clean_photos(payload.photos):
                if photo not in existing and photo not in added:
                    added.append(photo)
            if len(existing) + len(added) > MAX_PHOTOS:
                raise ApiError(
                    422,
                    "too_many_photos",
                    f"O leilão já tem {len(existing)} fotos; o máximo é {MAX_PHOTOS}.",
                )
            if added:
                await tx.item.update(
                    where={"id": auction.item_id},
                    data={"photos": existing + added},
                )

        if not changes and not added:
            raise ApiError(
                422,
                "nothing_to_update",
                "Envie uma nova duração ou pelo menos uma foto nova.",
            )

        if changes:
            await tx.auction.update(where={"id": auction_id}, data=changes)

    return auction_dict(await get_auction(db, auction_id))


async def relist_auction(
    db: Prisma, user: models.User, auction_id: str, payload: Any
) -> dict[str, Any]:
    """RF28: relista um item de leilão encerrado sem lances ou cancelado.

    Cria um novo leilão para o MESMO item, com todos os campos editáveis. Um
    item nunca fica com dois leilões agendados/em andamento ao mesmo tempo.
    """
    source = await get_auction(db, auction_id)
    if source.seller_id != user.id:
        raise ApiError(
            403, "not_seller", "Só o comitente pode relistar este leilão."
        )
    if status_value(source) not in {"unsold", "cancelled"}:
        raise ApiError(
            409,
            "not_relistable",
            "Só leilões encerrados sem lances ou cancelados podem ser relistados.",
        )

    fields = _auction_fields(payload)

    async with db.tx() as tx:
        # Serializa relistagens concorrentes do mesmo item.
        await tx.query_raw(
            'SELECT id FROM "items" WHERE id = $1 FOR UPDATE', source.item_id
        )
        active = await tx.auction.find_first(
            where={
                "item_id": source.item_id,
                "status": {
                    "in": [AuctionStatus.scheduled, AuctionStatus.running]
                },
            }
        )
        if active is not None:
            raise ApiError(
                409,
                "item_has_active_auction",
                "Este item já tem um leilão agendado ou em andamento.",
            )

        await tx.item.update(
            where={"id": source.item_id},
            data={
                "name": fields["name"],
                "description": fields["description"],
                "category": fields["category"],
                "photos": fields["photos"],
            },
        )
        created = await tx.auction.create(
            data={
                "item": {"connect": {"id": source.item_id}},
                "seller": {"connect": {"id": user.id}},
                "status": fields["status"],
                "starting_price_cents": payload.starting_price,
                "current_price_cents": payload.starting_price,
                "starts_at": fields["starts_at"],
                "ends_at": fields["ends_at"],
                "original_ends_at": fields["ends_at"],
            }
        )

    return auction_dict(await get_auction(db, created.id))


async def cancel_auction(
    db: Prisma, user: models.User, auction_id: str
) -> dict[str, Any]:
    await sync_auctions(db)

    # RF08/RF11: o cancelamento usa o mesmo lock de linha dos lances
    # (place_bid). Sem ele, um lance poderia entrar entre a leitura de
    # bid_count e o UPDATE, deixando o leilão cancelado com lances.
    async with db.tx(timeout=timedelta(seconds=10)) as tx:
        locked = await tx.query_raw(
            'SELECT id FROM "auctions" WHERE id = $1 FOR UPDATE',
            auction_id,
        )
        if not locked:
            raise ApiError(404, "auction_not_found", "Leilão não encontrado.")

        auction = await tx.auction.find_unique(
            where={"id": auction_id}, include=AUCTION_INCLUDE
        )
        if auction is None:
            raise ApiError(404, "auction_not_found", "Leilão não encontrado.")

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

        await tx.auction.update(
            where={"id": auction_id},
            data={"status": AuctionStatus.cancelled, "cancelled_at": utcnow()},
        )
        cancelled = await tx.auction.find_unique(
            where={"id": auction_id}, include=AUCTION_INCLUDE
        )
        if cancelled is None:
            raise ApiError(404, "auction_not_found", "Leilão não encontrado.")
        result = auction_dict(cancelled)

    return result


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
    in_room: Callable[[], bool] | None = None,
) -> tuple[models.Bid, models.Auction, bool]:
    """Grava um lance com lock de linha (RF10-RF14).

    Retorna (bid, auction, replay). O lock `FOR UPDATE` serializa lances
    simultâneos do mesmo leilão no Postgres.
    """
    bid_id: str | None = None
    replay = False

    async with db.tx(timeout=timedelta(seconds=10)) as tx:
        locked = await tx.query_raw(
            'SELECT id FROM "auctions" WHERE id = $1 FOR UPDATE', auction_id
        )
        if not locked:
            raise ApiError(404, "auction_not_found", "Leilão não encontrado.")
        # O relógio é lido DEPOIS de obter o lock. Antes era lido na entrada:
        # um lance que esperasse na fila usava um horário velho e podia ser
        # aceito após o fim do leilão (e errar o intervalo e a prorrogação).
        now = utcnow()

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
            # A chave só repete o resultado para quem a criou e com o mesmo
            # valor; senão um usuário receberia o lance de outro como se
            # fosse a confirmação do seu.
            if existing.bidder_id != user.id or existing.amount_cents != amount:
                raise ApiError(
                    409,
                    "idempotency_key_reused",
                    "Esta chave de idempotência já foi usada em outro lance.",
                )
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

            # RF10: o autor precisa estar na sala (WS aberto) neste instante.
            # Fica depois do replay para que um reenvio idempotente continue
            # devolvendo o resultado original mesmo se o socket tiver caído.
            if in_room is not None and not in_room():
                raise ApiError(
                    409,
                    "not_in_room",
                    "Entre na sala como participante para dar lance.",
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
                    "Seu lance ficou abaixo do mínimo.",
                    min_bid=minimum,
                )

            if ENFORCE_CREDIT:
                credit = await credit_info(tx, user)
                if amount > credit["credit_available_cents"]:
                    raise ApiError(
                        403,
                        "insufficient_credit",
                        "Crédito disponível insuficiente para este lance.",
                        extra={
                            "credit_available": credit["credit_available_cents"],
                            "min_bid": minimum,
                        },
                    )

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


def _now_iso() -> str:
    from .serializers import iso

    return iso(utcnow())
