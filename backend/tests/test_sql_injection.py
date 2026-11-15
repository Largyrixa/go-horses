#!/usr/bin/env python3
"""Tentativas de SQL injection contra a API do Go Horses (caixa-preta).

A API usa Prisma com consultas parametrizadas. Este script envia payloads
clássicos em query strings, path params, corpo JSON, login e Idempotency-Key e
verifica que:
  - nenhuma requisição retorna 5xx;
  - nenhuma resposta vaza stack trace/detalhes do banco;
  - payloads de tempo (pg_sleep) não são executados;
  - strings maliciosas são gravadas/retornadas literalmente;
  - a API continua saudável depois dos ataques.
"""
from __future__ import annotations

import asyncio
import sys
import time
from urllib.parse import quote

from common import (
    Checker,
    TEST_PASSWORD,
    auth_headers,
    auction_detail,
    build_parser,
    create_auction,
    ensure_api,
    error_code,
    looks_like_internal_leak,
    make_client,
    place_bid,
    register_user,
)

PAYLOADS = (
    "' OR '1'='1",
    "'; DROP TABLE \"users\"; --",
    '" OR 1=1 --',
    "1'; SELECT pg_sleep(5); --",
    "%' UNION SELECT id, email, password_hash FROM users --",
    "admin'--",
    "1; DELETE FROM bids; --",
    "') OR ('1'='1",
)
TIME_BASED = {"1'; SELECT pg_sleep(5); --"}
DROP_PAYLOAD = "'; DROP TABLE \"users\"; --"
KEY_PAYLOAD = "'; DROP TABLE bids; --"


def assert_safe(
    checker: Checker,
    label: str,
    response,
    elapsed: float,
    *,
    time_based: bool = False,
) -> None:
    checker.ok(
        f"{label} não retorna 5xx",
        response.status_code < 500,
        f"status={response.status_code}",
    )
    checker.ok(
        f"{label} sem vazamento interno",
        not looks_like_internal_leak(response.text),
    )
    if time_based:
        checker.ok(
            f"{label} não executa pg_sleep",
            elapsed < 4.0,
            f"levou {elapsed:.2f}s",
        )


async def main() -> int:
    args = build_parser(
        "Tentativas de SQL injection contra o Go Horses"
    ).parse_args()
    checker = Checker("SQL injection")

    async with make_client(args.base_url) as client:
        if not await ensure_api(client):
            return 2

        print("-- Preparando usuários e leilões --")
        seller = await register_user(
            client,
            "sqli-seller",
            display_name=DROP_PAYLOAD,
        )
        bidder = await register_user(client, "sqli-bidder")

        running = await create_auction(
            client,
            seller,
            name=f"Leilão SQLi {time.time_ns()}",
            starts_in=0,
            duration=120,
            starting_price=5_000,
        )
        literal = await create_auction(
            client,
            seller,
            name=DROP_PAYLOAD,
            description=f"Descrição {DROP_PAYLOAD}",
            starts_in=3_600,
            duration=300,
            starting_price=5_000,
        )

        print("\n-- Payloads em query string e path --")
        for index, payload in enumerate(PAYLOADS, start=1):
            is_time_based = payload in TIME_BASED

            started = time.perf_counter()
            response = await client.get("/api/auctions", params={"q": payload})
            elapsed = time.perf_counter() - started
            assert_safe(
                checker,
                f"q[{index}]={payload!r}",
                response,
                elapsed,
                time_based=is_time_based,
            )
            checker.equal(f"busca q[{index}] responde 200", response.status_code, 200)

            started = time.perf_counter()
            response = await client.get(
                "/api/auctions", params={"category": payload}
            )
            elapsed = time.perf_counter() - started
            assert_safe(
                checker,
                f"category[{index}]={payload!r}",
                response,
                elapsed,
                time_based=is_time_based,
            )
            checker.equal(
                f"categoria category[{index}] responde 200",
                response.status_code,
                200,
            )

            started = time.perf_counter()
            response = await client.get(
                "/api/auctions", params={"status": payload}
            )
            elapsed = time.perf_counter() - started
            assert_safe(
                checker,
                f"status[{index}]={payload!r}",
                response,
                elapsed,
                time_based=is_time_based,
            )
            checker.equal(
                f"status[{index}] inválido responde 422",
                response.status_code,
                422,
            )
            checker.is_in(
                f"status[{index}] retorna erro de validação coerente",
                error_code(response),
                ("invalid_status", "validation_error"),
            )

            encoded = quote(payload, safe="")
            started = time.perf_counter()
            response = await client.get(f"/api/auctions/{encoded}")
            elapsed = time.perf_counter() - started
            assert_safe(
                checker,
                f"GET /api/auctions/[payload {index}]",
                response,
                elapsed,
                time_based=is_time_based,
            )
            checker.equal(
                f"path de leilão [{index}] responde 404",
                response.status_code,
                404,
            )

            started = time.perf_counter()
            response = await client.get(f"/api/users/{encoded}")
            elapsed = time.perf_counter() - started
            assert_safe(
                checker,
                f"GET /api/users/[payload {index}]",
                response,
                elapsed,
                time_based=is_time_based,
            )
            checker.equal(
                f"path de usuário [{index}] responde 404",
                response.status_code,
                404,
            )

        response = await client.get(
            "/api/auctions", params={"status": "invalido"}
        )
        checker.equal(
            "status curto inválido responde 422",
            response.status_code,
            422,
        )
        checker.equal(
            "status curto inválido retorna invalid_status",
            error_code(response),
            "invalid_status",
        )

        print("\n-- Login e validação de tipos --")
        for index, payload in enumerate(PAYLOADS, start=1):
            started = time.perf_counter()
            response = await client.post(
                "/api/auth/login",
                json={"email": payload, "password": payload},
            )
            elapsed = time.perf_counter() - started
            assert_safe(
                checker,
                f"login[{index}] com payload",
                response,
                elapsed,
                time_based=payload in TIME_BASED,
            )
            checker.is_in(
                f"login[{index}] não autentica com payload",
                response.status_code,
                (401, 422),
            )

        response = await client.get("/api/auctions", params={"page": "1;DROP TABLE bids;--"})
        checker.equal("page com SQLi -> 422", response.status_code, 422)
        assert_safe(checker, "page com SQLi", response, 0.0)

        response = await client.post(
            f"/api/auctions/{running['id']}/bids",
            headers={
                **auth_headers(bidder),
                "Idempotency-Key": "amount-sqli",
            },
            json={"amount": "5000; DROP TABLE bids;--"},
        )
        checker.equal("amount como string SQLi -> 422", response.status_code, 422)
        assert_safe(checker, "amount como string SQLi", response, 0.0)

        print("\n-- Strings maliciosas gravadas literalmente --")
        response = await client.get("/api/auth/me", headers=auth_headers(seller))
        checker.equal(
            "display_name malicioso volta literal",
            response.json().get("display_name"),
            DROP_PAYLOAD,
        )

        checker.equal("nome do leilão volta literal", literal["name"], DROP_PAYLOAD)
        checker.equal(
            "descrição do leilão volta literal",
            literal["description"],
            f"Descrição {DROP_PAYLOAD}",
        )

        print("\n-- Idempotency-Key com payload SQL --")
        min_bid = running["min_bid"]
        started = time.perf_counter()
        response = await place_bid(
            client,
            bidder,
            running["id"],
            min_bid,
            KEY_PAYLOAD,
        )
        elapsed = time.perf_counter() - started
        assert_safe(
            checker,
            "lance com Idempotency-Key SQLi",
            response,
            elapsed,
        )
        checker.equal("lance com chave maliciosa -> 201", response.status_code, 201)
        if response.status_code == 201:
            first_bid_id = response.json()["bid"]["id"]
            response = await place_bid(
                client,
                bidder,
                running["id"],
                min_bid,
                KEY_PAYLOAD,
            )
            checker.equal("reenvio da chave maliciosa -> 201", response.status_code, 201)
            if response.status_code == 201:
                replay = response.json()
                checker.equal("reenvio é marcado como replay", replay.get("replayed"), True)
                checker.equal("reenvio devolve o mesmo lance", replay["bid"]["id"], first_bid_id)
                checker.equal("reenvio mantém o valor", replay["bid"]["amount"], min_bid)

        detail = await auction_detail(client, running["id"])
        checker.equal("banco registrou apenas um lance", detail["bid_count"], 1)
        checker.equal("preço atual é o lance válido", detail["current_price"], min_bid)

        print("\n-- Integridade após os ataques --")
        response = await client.get("/api/health")
        checker.equal("API continua saudável", response.status_code, 200)

        response = await client.post(
            "/api/auth/login",
            json={"email": seller.email, "password": TEST_PASSWORD},
        )
        checker.equal("tabela users continua íntegra (login funciona)", response.status_code, 200)

        response = await client.get("/api/auctions")
        checker.equal("listagem continua funcionando", response.status_code, 200)
        checker.ok(
            "listagem não vazou detalhes internos",
            not looks_like_internal_leak(response.text),
        )

        response = await client.post(
            f"/api/auctions/{literal['id']}/cancel",
            headers=auth_headers(seller),
        )
        checker.equal("limpeza do leilão literal -> 200", response.status_code, 200)

    return checker.finish()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
