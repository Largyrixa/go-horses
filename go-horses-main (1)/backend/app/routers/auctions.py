"""Categorias, leilões, lances e sala em tempo real."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, WebSocket, WebSocketDisconnect

from ..auction_service import (
    cancel_auction,
    create_auction,
    get_auction,
    list_auctions,
    place_bid,
    room_payload,
)
from ..config import CATEGORIES, IDEMPOTENCY_HEADER
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
    iso,
    utcnow,
)

router = APIRouter(tags=["auctions"])


@router.get("/categories")
async def categories():
    return CATEGORIES


@router.get("/auctions")
async def auctions(
    q: str = Query(default=""),
    category: str = Query(default=""),
    status: str = Query(default=""),
    page: int = Query(default=1, ge=1),
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


@router.websocket("/auctions/{auction_id}/ws")
async def auction_ws(
    websocket: WebSocket,
    auction_id: str,
    token: str | None = None,
    role: str = "spectator",
):
    if role not in {"participant", "spectator"}:
        role = "spectator"
    if not token:
        await websocket.accept()
        await websocket.close(code=4401)
        return

    session = await db.session.find_unique(
        where={"token_hash": hash_session_token(token)},
        include={"user": True},
    )
    if session is None or ensure_utc(session.expires_at) <= utcnow():
        await websocket.accept()
        await websocket.close(code=4401)
        return

    auction = await db.auction.find_unique(where={"id": auction_id})
    if auction is None:
        await websocket.accept()
        await websocket.close(code=4404)
        return
    # RF04/RF25: o comitente só assiste ao próprio leilão.
    if auction.seller_id == session.user_id:
        role = "spectator"

    user = session.user

    await websocket.accept()
    client = Client(
        websocket=websocket,
        auction_id=auction_id,
        user_id=session.user_id,
        role=role,
    )
    await rooms.add(client)
    last_chat = 0.0
    try:
        await rooms.broadcast_state(auction_id)

        # Histórico do chat para quem entra no meio do leilão.
        history = await db.chatmessage.find_many(
            where={"auction_id": auction_id},
            include={"user": True},
            order={"created_at": "desc"},
            take=50,
        )
        await websocket.send_json(
            {
                "type": "chat_history",
                "messages": [
                    {
                        "id": m.id,
                        "text": m.text,
                        "created_at": iso(m.created_at),
                        "user": {"id": m.user.id, "display_name": m.user.display_name},
                    }
                    for m in reversed(history)
                ],
            }
        )

        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(data, dict) or data.get("type") != "chat":
                continue

            text = str(data.get("text", "")).strip()[:300]
            now = time.monotonic()
            if not text or now - last_chat < 1.0:
                continue
            last_chat = now

            msg = await db.chatmessage.create(
                data={
                    "auction_id": auction_id,
                    "user": {"connect": {"id": user.id}},
                    "text": text,
                },
                include={"user": True},
            )
            await rooms.broadcast_chat(
                auction_id,
                {
                    "id": msg.id,
                    "text": msg.text,
                    "created_at": iso(msg.created_at),
                    "user": {"id": user.id, "display_name": user.display_name},
                },
            )
    except WebSocketDisconnect:
        pass
    finally:
        await rooms.remove(client)
        await rooms.broadcast_counts(auction_id)