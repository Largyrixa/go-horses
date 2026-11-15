#!/usr/bin/env python3
"""Testes das funcionalidades novas: RF23 (edição), RF28 (relistagem),
RF22 (perfil/busca de comitentes) e RF10 (presença na sala para lance)."""
from __future__ import annotations

import asyncio
import sys

from common import (
    Checker,
    auth_headers,
    build_parser,
    create_auction,
    ensure_api,
    error_code,
    iso_utc,
    join_room,
    make_client,
    place_bid,
    preview,
    register_user,
)


def relist_payload(name: str) -> dict:
    return {
        "name": name,
        "description": "Item relistado pela suíte de testes.",
        "category": "Outros",
        "photos": [
            "/static/demo/quadro-1.svg",
            "/static/demo/quadro-2.svg",
            "/static/demo/quadro-3.svg",
        ],
        "starting_price": 12_000,
        "starts_at": iso_utc(600),
        "duration_seconds": 300,
    }


async def main() -> int:
    args = build_parser(
        "Testes de RF23/RF28/perfil/sala do Go Horses"
    ).parse_args()
    checker = Checker("RF23/RF28/perfil/sala")

    async with make_client(args.base_url) as client:
        if not await ensure_api(client):
            return 2

        print("-- Preparando usuários --")
        seller = await register_user(client, "feat-seller")
        buyer = await register_user(client, "feat-buyer")

        print("\n-- RF23: edição de leilão --")
        scheduled = await create_auction(
            client,
            seller,
            name="Leilão editável",
            starts_in=600,
            duration=300,
        )
        original_ends = scheduled["ends_at"]

        response = await client.patch(
            f"/api/auctions/{scheduled['id']}",
            headers=auth_headers(buyer),
            json={"duration_seconds": 900},
        )
        checker.equal("Não comitente edita leilão -> 403", response.status_code, 403)
        checker.equal("Edição indevida retorna not_seller", error_code(response), "not_seller")

        response = await client.patch(
            f"/api/auctions/{scheduled['id']}",
            headers=auth_headers(seller),
            json={"duration_seconds": 900},
        )
        checker.equal("Comitente altera duração -> 200", response.status_code, 200)
        if response.status_code == 200:
            updated = response.json()
            checker.ok("A duração altera o término", updated["ends_at"] != original_ends)

        response = await client.patch(
            f"/api/auctions/{scheduled['id']}",
            headers=auth_headers(seller),
            json={"photos": ["/static/demo/quadro-1.svg"]},
        )
        checker.equal("Comitente anexa foto -> 200", response.status_code, 200)
        if response.status_code == 200:
            checker.equal("O leilão fica com 4 fotos", len(response.json()["photos"]), 4)

        response = await client.patch(
            f"/api/auctions/{scheduled['id']}",
            headers=auth_headers(seller),
            json={},
        )
        checker.equal("PATCH sem mudanças -> 422", response.status_code, 422)
        checker.equal("PATCH vazio retorna nothing_to_update", error_code(response), "nothing_to_update")

        response = await client.patch(
            f"/api/auctions/{scheduled['id']}",
            headers=auth_headers(seller),
            json={"photos": ["https://example.com/foto.jpg"]},
        )
        checker.equal("PATCH com foto externa -> 422", response.status_code, 422)
        checker.equal("Foto externa retorna invalid_photos", error_code(response), "invalid_photos")

        running = await create_auction(
            client,
            seller,
            name="Leilão em andamento editável",
            starts_in=0,
            duration=300,
        )
        response = await client.patch(
            f"/api/auctions/{running['id']}",
            headers=auth_headers(seller),
            json={"duration_seconds": 600},
        )
        checker.equal("Duração de leilão aberto -> 409", response.status_code, 409)
        checker.equal("Duração travada retorna duration_locked", error_code(response), "duration_locked")

        response = await client.patch(
            f"/api/auctions/{running['id']}",
            headers=auth_headers(seller),
            json={"photos": ["/static/demo/quadro-2.svg"]},
        )
        checker.equal("Fotos em leilão aberto -> 200", response.status_code, 200)

        print("\n-- RF28: relistagem --")
        source = await create_auction(
            client,
            seller,
            name="Leilão para relistar",
            starts_in=600,
            duration=300,
        )
        response = await client.post(
            f"/api/auctions/{source['id']}/cancel",
            headers=auth_headers(seller),
        )
        checker.equal("Cancelamento da origem -> 200", response.status_code, 200)

        payload = relist_payload("Leilão relistado")
        response = await client.post(
            f"/api/auctions/{source['id']}/relist",
            headers=auth_headers(buyer),
            json=payload,
        )
        checker.equal("Não comitente relista -> 403", response.status_code, 403)
        checker.equal("Relistagem indevida retorna not_seller", error_code(response), "not_seller")

        response = await client.post(
            f"/api/auctions/{source['id']}/relist",
            headers=auth_headers(seller),
            json=payload,
        )
        checker.equal("Relistagem do comitente -> 201", response.status_code, 201)
        new_auction = response.json() if response.status_code == 201 else {}
        if new_auction:
            checker.ok("Relistagem cria outro leilão", new_auction.get("id") != source["id"])
            checker.equal("Relistagem usa o novo nome", new_auction.get("name"), payload["name"])
            checker.equal("Relistagem nasce agendada", new_auction.get("status"), "scheduled")

        response = await client.post(
            f"/api/auctions/{new_auction['id']}/relist",
            headers=auth_headers(seller),
            json=payload,
        )
        checker.equal("Relaistar leilão ativo -> 409", response.status_code, 409)
        checker.equal("Leilão ativo retorna not_relistable", error_code(response), "not_relistable")

        response = await client.post(
            f"/api/auctions/{source['id']}/relist",
            headers=auth_headers(seller),
            json=payload,
        )
        checker.equal("Relaistar item com leilão ativo -> 409", response.status_code, 409)
        checker.equal(
            "Item ativo retorna item_has_active_auction",
            error_code(response),
            "item_has_active_auction",
        )

        print("\n-- RF22: busca e perfil público --")
        response = await client.get("/api/users", params={"q": seller.display_name})
        checker.equal("Busca de comitentes -> 200", response.status_code, 200)
        items = response.json().get("items", []) if response.status_code == 200 else []
        checker.ok(
            "Busca encontra o comitente",
            any(item.get("id") == seller.id for item in items),
        )
        checker.ok("Busca não expõe e-mail", all("email" not in item for item in items))
        checker.ok(
            "Busca devolve nome mascarado",
            all(item.get("display_name") != seller.display_name for item in items),
        )

        response = await client.get("/api/users", params={"q": "a"})
        checker.equal("Busca curta devolve lista vazia", len(response.json().get("items", [])), 0)

        response = await client.get(f"/api/users/{seller.id}")
        checker.equal("Perfil público -> 200", response.status_code, 200)
        if response.status_code == 200:
            profile = response.json()
            checker.ok("Perfil não expõe e-mail", "email" not in profile)
            checker.ok("Perfil lista leilões do comitente", len(profile.get("auctions", [])) > 0)

        print("\n-- RF10: presença na sala para dar lance --")
        room_auction = await create_auction(
            client,
            seller,
            name="Leilão com exigência de sala",
            starts_in=0,
            duration=300,
            starting_price=5_000,
        )
        amount = room_auction["min_bid"]

        response = await place_bid(
            client,
            buyer,
            room_auction["id"],
            amount,
            "bid-sem-sala",
        )
        checker.equal("Lance sem estar na sala -> 409", response.status_code, 409)
        checker.equal("Lance sem sala retorna not_in_room", error_code(response), "not_in_room")

        room = await join_room(args.base_url, room_auction["id"], buyer)
        try:
            response = await place_bid(
                client,
                buyer,
                room_auction["id"],
                amount,
                "bid-com-sala",
            )
        finally:
            await room.close()
        checker.equal("Lance com a sala aberta -> 201", response.status_code, 201)

    return checker.finish()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
