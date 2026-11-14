"""Área do usuário: meus leilões, participações e perfil público."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from prisma.enums import AuctionStatus

from ..auction_service import AUCTION_INCLUDE, sync_auctions
from ..db import db
from ..deps import get_current_user
from ..errors import ApiError
from ..serializers import auction_dict, user_dict

router = APIRouter(tags=["me"])


@router.get("/me/auctions")
async def my_auctions(user=Depends(get_current_user)):
    await sync_auctions(db)
    rows = await db.auction.find_many(
        where={"seller_id": user.id},
        include=AUCTION_INCLUDE,
        order={"created_at": "desc"},
    )
    return {"items": [auction_dict(auction) for auction in rows]}


@router.get("/me/participations")
async def my_participations(user=Depends(get_current_user)):
    """RF27: leilões em que o usuário deu lance + situação (líder/superado/vencedor)."""
    await sync_auctions(db)
    bids = await db.bid.find_many(
        where={"bidder_id": user.id},
        order={"amount_cents": "desc"},
    )
    top_by_auction: dict[str, int] = {}
    for bid in bids:
        top_by_auction.setdefault(bid.auction_id, bid.amount_cents)
    if not top_by_auction:
        return {"items": []}

    rows = await db.auction.find_many(
        where={"id": {"in": list(top_by_auction)}},
        include=AUCTION_INCLUDE,
        order={"updated_at": "desc"},
    )
    items = []
    for auction in rows:
        if auction.status == AuctionStatus.sold and auction.winner_id == user.id:
            situation = "won"
        elif (
            auction.status == AuctionStatus.running
            and auction.leader_id == user.id
        ):
            situation = "leader"
        else:
            situation = "outbid"
        items.append(
            {
                "auction": auction_dict(auction),
                "situation": situation,
                "my_top_bid": top_by_auction.get(auction.id, 0),
            }
        )
    return {"items": items}


@router.get("/users/{user_id}")
async def public_profile(user_id: str):
    """RF22: perfil público do comitente (sem e-mail)."""
    user = await db.user.find_unique(where={"id": user_id})
    if user is None:
        raise ApiError(404, "user_not_found", "Usuário não encontrado.")
    await sync_auctions(db)
    rows = await db.auction.find_many(
        where={"seller_id": user_id},
        include=AUCTION_INCLUDE,
        order={"created_at": "desc"},
    )
    return {
        **user_dict(user, include_email=False),
        "auctions": [auction_dict(auction) for auction in rows],
    }
