"""Categorias, leilões, lances e sala em tempo real."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Header, Query, WebSocket, WebSocketDisconnect

from ..auction_service import (
    cancel_auction,
    create_auction,
    get_auction,
    list_auctions,
    place_bid,
    room_payload,
)
from ..config import (
    CATEGORIES,
    IDEMPOTENCY_HEADER,
    MAX_IDEMPOTENCY_KEY_LENGTH,
    MAX_PAGE,
    MAX_SEARCH_LENGTH,
    WS_AUTH_TIMEOUT_SECONDS,
)
from ..db import db
from ..deps import get_current_user
from ..errors import ApiError
from ..realtime import Client, rooms
from ..schemas import AuctionCreateIn, BidIn
from ..security import hash_session_token
from ..serializers import (
    auction_dict,
    bid_dict,
    ensure_utc,
    utcnow,
)

router = APIRouter(tags=["auctions"])


@router.get("/categories")
async def categories():
    return CATEGORIES


@router.get("/auctions")
async def auctions(
    q: str = Query(default="", max_length=MAX_SEARCH_LENGTH),
    category: str = Query(default="", max_length=60),
    status: str = Query(default="", max_length=20),
    # Teto na página: um número gigante estourava o OFFSET e virava erro 500.
    page: int = Query(default=1, ge=1, le=MAX_PAGE),
):
    return await list_auctions(
        db, q=q, category=category, status=status, page=page
    )


@router.get("/auctions/{auction_id}")
async def auction_detail(auction_id: str):
    from ..auction_service import sync_auctions

    await sync_auctions(db)
    auction = await get_auction(db, auction_id)
    return auction_dict(auction)


@router.post("/auctions", status_code=201)
async def create(payload: AuctionCreateIn, user=Depends(get_current_user)):
    created = await create_auction(db, user, payload)
    return created


@router.post("/auctions/{auction_id}/cancel")
async def cancel(auction_id: str, user=Depends(get_current_user)):
    result = await cancel_auction(db, user, auction_id)
    await rooms.broadcast_state(auction_id)
    return result


@router.get("/auctions/{auction_id}/room")
async def room(auction_id: str, user=Depends(get_current_user)):
    counts = rooms.counts(auction_id)
    return await room_payload(db, auction_id, **counts)


@router.post("/auctions/{auction_id}/bids", status_code=201)
async def bid(
    auction_id: str,
    payload: BidIn,
    idempotency_key: str = Header(alias=IDEMPOTENCY_HEADER),
    user=Depends(get_current_user),
):
    if not idempotency_key.strip():
        raise ApiError(
            422,
            "missing_idempotency_key",
            "Envie o cabeçalho Idempotency-Key.",
        )
    if len(idempotency_key.strip()) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise ApiError(
            422,
            "invalid_idempotency_key",
            "Cabeçalho Idempotency-Key longo demais.",
        )
    bid_record, auction, replay = await place_bid(
        db,
        user,
        auction_id,
        payload.amount,
        idempotency_key.strip(),
    )
    await rooms.broadcast_state(auction_id)
    return {
        "bid": bid_dict(bid_record),
        "auction": auction_dict(auction),
        "replayed": replay,
    }


async def _ws_first_message_token(websocket: WebSocket) -> str | None:
    """Lê o token da primeira mensagem: {"type": "auth", "token": "..."}."""
    try:
        raw = await asyncio.wait_for(
            websocket.receive_text(), timeout=WS_AUTH_TIMEOUT_SECONDS
        )
        message = json.loads(raw)
    except (asyncio.TimeoutError, ValueError, KeyError, RuntimeError):
        return None
    if not isinstance(message, dict) or message.get("type") != "auth":
        return None
    token = message.get("token")
    return token.strip() if isinstance(token, str) and token.strip() else None


@router.websocket("/auctions/{auction_id}/ws")
async def auction_ws(
    websocket: WebSocket,
    auction_id: str,
    token: str | None = None,
    role: str = "spectator",
):
    if role not in {"participant", "spectator"}:
        role = "spectator"

    # O front manda o token na primeira mensagem, não na URL: query string
    # aparece nos logs de acesso (uvicorn/proxy) e exporia a sessão. O
    # parâmetro `token` continua aceito para clientes antigos e scripts.
    await websocket.accept()
    try:
        if not token:
            token = await _ws_first_message_token(websocket)
        if not token:
            await websocket.close(code=4401)
            return

        session = await db.session.find_unique(
            where={"token_hash": hash_session_token(token)},
            include={"user": True},
        )
        if (
            session is None
            or session.user is None
            or ensure_utc(session.expires_at) <= utcnow()
        ):
            await websocket.close(code=4401)
            return

        auction = await db.auction.find_unique(where={"id": auction_id})
        if auction is None:
            await websocket.close(code=4404)
            return
    except WebSocketDisconnect:
        return
    # RF04/RF25: o comitente só assiste ao próprio leilão.
    if auction.seller_id == session.user_id:
        role = "spectator"

    client = Client(
        websocket=websocket,
        auction_id=auction_id,
        user_id=session.user_id,
        role=role,
    )
    await rooms.add(client)
    try:
        await rooms.broadcast_state(auction_id)
        while True:
            # Nada do que o cliente manda depois da autenticação é usado; só
            # mantemos a leitura para perceber a desconexão.
            await websocket.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await rooms.remove(client)
        await rooms.broadcast_counts(auction_id)
