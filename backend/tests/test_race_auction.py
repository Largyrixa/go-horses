#!/usr/bin/env python3
"""Testes de concorrência de leilões do Go Horses (caixa-preta).

Cenários:
  1. Vários usuários enviam o mesmo lance mínimo ao mesmo tempo.
  2. Vários usuários disputam o novo lance mínimo ao mesmo tempo.
  3. Mesmo usuário reenvia a mesma Idempotency-Key em paralelo.
  4. Mesma chave com valor diferente é recusada (idempotency_key_reused).
  5. Corrida entre cancelamento e lance: o leilão não pode ficar cancelado
     com lances.

O script reporta violações de invariantes; ele não corrige a aplicação.
"""
from __future__ import annotations

import asyncio
import sys
import uuid

from common import (
    Checker,
    auth_headers,
    auction_detail,
    build_parser,
    create_auction,
    ensure_api,
    error_code,
    join_room,
    make_client,
    place_bid,
    preview,
    register_user,
)


async def fire_bids(client, users, auction_id, amount, prefix):
    """Dispara um lance por usuário ao mesmo tempo.

    Retorna (respostas, exceções). Exceções de transporte não abortam a rodada.
    """
    results = await asyncio.gather(
        *(
            place_bid(
                client,
                user,
                auction_id,
                amount,
                f"{prefix}-{index}-{uuid.uuid4().hex[:8]}",
            )
            for index, user in enumerate(users)
        ),
        return_exceptions=True,
    )
    exceptions = [item for item in results if isinstance(item, BaseException)]
    responses = [item for item in results if not isinstance(item, BaseException)]
    return responses, exceptions


async def run_bid_round(
    checker: Checker,
    client,
    bidders,
    auction_id: str,
    amount: int,
    prefix: str,
    expected_count: int,
):
    print(f"\n-- {prefix}: {len(bidders)} lances simultâneos em {amount} centavos --")
    responses, exceptions = await fire_bids(
        client, bidders, auction_id, amount, prefix
    )
    checker.equal(f"{prefix}: sem erros de transporte", len(exceptions), 0)
    if exceptions:
        print(f"         exceções: {exceptions[:3]}")

    accepted = [response for response in responses if response.status_code == 201]
    rejected = [response for response in responses if response.status_code != 201]
    checker.equal(f"{prefix}: exatamente um lance aceito", len(accepted), 1)

    for index, response in enumerate(rejected, start=1):
        checker.is_in(
            f"{prefix}: rejeitado #{index} retorna 409/429",
            response.status_code,
            (409, 429),
        )
        checker.is_in(
            f"{prefix}: rejeitado #{index} tem código coerente",
            error_code(response),
            ("bid_too_low", "already_leading", "bid_too_fast"),
        )
        if response.status_code not in (409, 429):
            print(f"         resposta: {preview(response)}")

    detail = await auction_detail(client, auction_id)
    checker.equal(
        f"{prefix}: bid_count após a rodada",
        detail["bid_count"],
        expected_count,
    )
    checker.equal(
        f"{prefix}: preço atual é o lance vencedor",
        detail["current_price"],
        amount,
    )

    accepted_body = None
    if accepted:
        accepted_body = accepted[0].json()
        leader = detail.get("leader") or {}
        checker.equal(
            f"{prefix}: líder é o vencedor da rodada",
            leader.get("id"),
            accepted_body["bid"]["bidder"]["id"],
        )
    return accepted_body, detail


async def run_idempotency_round(
    checker: Checker,
    client,
    bidders,
    auction_id: str,
    accepted_ids: set[str],
) -> tuple[dict, int | None]:
    print("\n-- Mesma Idempotency-Key enviada 5 vezes em paralelo --")
    detail = await auction_detail(client, auction_id)
    leader_id = (detail.get("leader") or {}).get("id")
    candidates = [
        user
        for user in bidders
        if user.id != leader_id and user.id not in accepted_ids
    ]
    if not candidates:
        candidates = [user for user in bidders if user.id != leader_id]
    if not candidates:
        checker.ok("Idempotência concorrente", False, "sem usuário elegível")
        return detail, None

    candidate = candidates[0]
    amount = detail["min_bid"]
    key = f"idem-{uuid.uuid4().hex}"
    before_count = detail["bid_count"]

    results = await asyncio.gather(
        *(
            place_bid(client, candidate, auction_id, amount, key)
            for _ in range(5)
        ),
        return_exceptions=True,
    )
    exceptions = [item for item in results if isinstance(item, BaseException)]
    responses = [item for item in results if not isinstance(item, BaseException)]

    checker.equal("Idempotência: sem erros de transporte", len(exceptions), 0)
    checker.equal(
        "Idempotência: todas as requisições aceitas",
        len([response for response in responses if response.status_code == 201]),
        5,
    )

    bodies = [response.json() for response in responses if response.status_code == 201]
    if len(bodies) == 5:
        ids = {body["bid"]["id"] for body in bodies}
        amounts = {body["bid"]["amount"] for body in bodies}
        replays = [body["replayed"] for body in bodies]
        checker.equal("Idempotência: um único id de lance", len(ids), 1)
        checker.equal("Idempotência: um único valor de lance", amounts, {amount})
        checker.equal(
            "Idempotência: exatamente uma requisição original",
            replays.count(False),
            1,
        )
        checker.equal(
            "Idempotência: as outras quatro são replay",
            replays.count(True),
            4,
        )
    else:
        for response in responses:
            if response.status_code != 201:
                print(
                    f"         {response.status_code}: {preview(response)}"
                )

    after = await auction_detail(client, auction_id)
    checker.equal(
        "Idempotência: apenas um lance novo no banco",
        after["bid_count"],
        before_count + 1,
    )
    checker.equal(
        "Idempotência: usuário virou líder",
        (after.get("leader") or {}).get("id"),
        candidate.id,
    )

    if bodies:
        response = await place_bid(
            client,
            candidate,
            auction_id,
            amount + 10_000,
            key,
        )
        checker.equal(
            "Mesma chave com valor diferente -> 409",
            response.status_code,
            409,
        )
        checker.equal(
            "Mesma chave com valor diferente retorna idempotency_key_reused",
            error_code(response),
            "idempotency_key_reused",
        )
        unchanged = await auction_detail(client, auction_id)
        checker.equal(
            "Mesma chave não cria segundo lance",
            unchanged["bid_count"],
            before_count + 1,
        )
        checker.equal(
            "Mesma chave não altera o preço atual",
            unchanged["current_price"],
            amount,
        )
    return after, amount


async def run_cancel_race_round(
    checker: Checker,
    base_url: str,
    client,
    seller,
    bidder,
    index: int,
) -> None:
    auction = await create_auction(
        client,
        seller,
        name=f"Corrida cancelamento x lance {index}",
        starts_in=0,
        duration=60,
        starting_price=10_000,
    )
    auction_id = auction["id"]
    amount = auction["min_bid"]
    key = f"cancel-race-{index}-{uuid.uuid4().hex[:8]}"
    room = await join_room(base_url, auction_id, bidder)

    cancel_coro = client.post(
        f"/api/auctions/{auction_id}/cancel",
        headers=auth_headers(seller),
    )
    bid_coro = place_bid(client, bidder, auction_id, amount, key)
    results = await asyncio.gather(
        cancel_coro,
        bid_coro,
        return_exceptions=True,
    )
    exceptions = [item for item in results if isinstance(item, BaseException)]
    if exceptions:
        checker.ok(
            f"Corrida cancel x lance #{index}: sem erro de transporte",
            False,
            repr(exceptions[0]),
        )
        await room.close()
        return

    cancel_response, bid_response = results
    cancel_ok = cancel_response.status_code == 200
    bid_ok = bid_response.status_code == 201
    checker.ok(
        f"Corrida cancel x lance #{index}: exatamente uma operação venceu",
        cancel_ok != bid_ok,
        (
            f"cancel={cancel_response.status_code} "
            f"({error_code(cancel_response)}) "
            f"bid={bid_response.status_code} "
            f"({error_code(bid_response)})"
        ),
    )

    if not cancel_ok:
        checker.equal(
            f"Corrida cancel x lance #{index}: cancelamento perdedor retorna has_bids",
            error_code(cancel_response),
            "has_bids",
        )
    if not bid_ok:
        checker.equal(
            f"Corrida cancel x lance #{index}: lance perdedor retorna auction_closed",
            error_code(bid_response),
            "auction_closed",
        )

    detail = await auction_detail(client, auction_id)
    status = detail["status"]
    bid_count = detail["bid_count"]
    if status == "cancelled":
        checker.equal(
            f"Corrida cancel x lance #{index}: cancelado não tem lances",
            bid_count,
            0,
        )
    elif status == "running":
        checker.equal(
            f"Corrida cancel x lance #{index}: em andamento tem um lance",
            bid_count,
            1,
        )
    else:
        checker.ok(
            f"Corrida cancel x lance #{index}: estado final coerente",
            False,
            f"status={status}, bid_count={bid_count}",
        )

    if status == "running" and bid_count == 0:
        cleanup = await client.post(
            f"/api/auctions/{auction_id}/cancel",
            headers=auth_headers(seller),
        )
        checker.equal(
            f"Corrida cancel x lance #{index}: limpeza do leilão vazio",
            cleanup.status_code,
            200,
        )
    await room.close()


async def run_cancel_first_check(
    checker: Checker,
    base_url: str,
    client,
    seller,
    bidder,
) -> None:
    """Caminho determinístico: cancelamento concluído antes do lance."""
    print("\n-- Cancelamento antes do lance (caminho determinístico) --")
    auction = await create_auction(
        client,
        seller,
        name="Cancelamento antes do lance",
        starts_in=0,
        duration=60,
        starting_price=10_000,
    )
    auction_id = auction["id"]
    room = await join_room(base_url, auction_id, bidder)

    response = await client.post(
        f"/api/auctions/{auction_id}/cancel",
        headers=auth_headers(seller),
    )
    checker.equal("Cancelamento prévio -> 200", response.status_code, 200)

    response = await place_bid(
        client,
        bidder,
        auction_id,
        auction["min_bid"],
        f"cancel-first-{uuid.uuid4().hex[:8]}",
    )
    checker.equal("Lance em leilão já cancelado -> 409", response.status_code, 409)
    checker.equal(
        "Lance em leilão já cancelado retorna auction_closed",
        error_code(response),
        "auction_closed",
    )

    detail = await auction_detail(client, auction_id)
    checker.equal("Leilão cancelado não registra lance", detail["bid_count"], 0)
    checker.equal("Status continua cancelled", detail["status"], "cancelled")
    await room.close()


async def main() -> int:
    parser = build_parser(
        "Testes de concorrência de leilões do Go Horses"
    )
    parser.add_argument(
        "--bidders",
        type=int,
        default=8,
        help="quantidade de compradores concorrentes (padrão: 8)",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=5,
        help="rodadas da corrida cancelamento x lance (padrão: 5)",
    )
    args = parser.parse_args()
    if args.bidders < 2:
        parser.error("--bidders deve ser pelo menos 2")
    if args.rounds < 1:
        parser.error("--rounds deve ser pelo menos 1")

    checker = Checker("Corridas de leilão")
    async with make_client(
        args.base_url, concurrency=max(20, args.bidders + 8)
    ) as client:
        if not await ensure_api(client):
            return 2

        print("-- Preparando usuários e leilão principal --")
        seller = await register_user(client, "race-seller")
        bidders = [
            await register_user(client, f"race-bidder-{index}")
            for index in range(args.bidders)
        ]
        auction = await create_auction(
            client,
            seller,
            name="Leilão de corrida de lances",
            starts_in=0,
            duration=300,
            starting_price=10_000,
        )
        auction_id = auction["id"]
        detail = await auction_detail(client, auction_id)
        accepted_ids: set[str] = set()
        main_rooms = [
            await join_room(args.base_url, auction_id, bidder)
            for bidder in bidders
        ]

        first_amount = detail["min_bid"]
        first_body, detail = await run_bid_round(
            checker,
            client,
            bidders,
            auction_id,
            first_amount,
            "Rodada 1",
            expected_count=1,
        )
        if first_body:
            accepted_ids.add(first_body["bid"]["bidder"]["id"])

        await asyncio.sleep(0.6)
        second_amount = detail["min_bid"]
        second_body, detail = await run_bid_round(
            checker,
            client,
            bidders,
            auction_id,
            second_amount,
            "Rodada 2",
            expected_count=2,
        )
        if second_body:
            accepted_ids.add(second_body["bid"]["bidder"]["id"])

        await asyncio.sleep(0.6)
        detail, expected_price = await run_idempotency_round(
            checker,
            client,
            bidders,
            auction_id,
            accepted_ids,
        )

        print("\n-- Corrida entre cancelamento e lance --")
        for index in range(1, args.rounds + 1):
            bidder = bidders[(index - 1) % len(bidders)]
            await run_cancel_race_round(
                checker,
                args.base_url,
                client,
                seller,
                bidder,
                index,
            )

        await run_cancel_first_check(
            checker, args.base_url, client, seller, bidders[0]
        )

        detail = await auction_detail(client, auction_id)
        checker.equal(
            "Leilão principal terminou com 3 lances",
            detail["bid_count"],
            3,
        )
        if expected_price is not None:
            checker.equal(
                "Preço final do leilão principal é o último lance aceito",
                detail["current_price"],
                expected_price,
            )

        response = await client.get(
            f"/api/auctions/{auction_id}/room",
            headers=auth_headers(seller),
        )
        checker.equal("Sala do leilão -> 200", response.status_code, 200)
        if response.status_code == 200:
            checker.equal(
                "Sala expõe os 3 lances recentes",
                len(response.json().get("recent_bids", [])),
                3,
            )

        await asyncio.gather(
            *(room.close() for room in main_rooms),
            return_exceptions=True,
        )

    return checker.finish()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
