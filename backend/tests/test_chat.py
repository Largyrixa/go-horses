#!/usr/bin/env python3
"""Teste do chat ao vivo da sala do leilão (WebSocket).

Verifica que uma mensagem enviada por um participante chega aos demais e ao
GET /auctions/{id}/room, com o nome mascarado e sem e-mail.
"""
from __future__ import annotations

import asyncio
import json
import sys

from common import (
    Checker,
    auth_headers,
    build_parser,
    create_auction,
    ensure_api,
    make_client,
    register_user,
    websocket_url,
)


async def _await_chat(websocket, timeout: float = 10.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise TimeoutError("chat não chegou a tempo")
        raw = await asyncio.wait_for(websocket.recv(), timeout=remaining)
        try:
            message = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(message, dict) and message.get("type") == "chat":
            return message


async def main() -> int:
    args = build_parser("Teste do chat ao vivo do Go Horses").parse_args()
    checker = Checker("Chat ao vivo")

    async with make_client(args.base_url) as client:
        if not await ensure_api(client):
            return 2

        import websockets

        seller = await register_user(client, "chat-seller")
        user_a = await register_user(client, "chat-a")
        user_b = await register_user(client, "chat-b")

        auction = await create_auction(
            client,
            seller,
            name="Leilão com chat",
            starts_in=0,
            duration=300,
            starting_price=5_000,
        )

        async def open_ws(user):
            ws = await websockets.connect(
                websocket_url(
                    args.base_url,
                    auction["id"],
                    token=user.token,
                    role="participant",
                ),
                open_timeout=10,
                close_timeout=10,
            )
            # Primeira mensagem confirma a entrada na sala.
            first = await asyncio.wait_for(ws.recv(), timeout=10)
            checker.ok(
                f"{user.email[:10]} entra na sala",
                "auction" in json.loads(first or "{}"),
            )
            return ws

        ws_a = await open_ws(user_a)
        ws_b = await open_ws(user_b)

        try:
            await ws_a.send(json.dumps({"type": "chat", "text": "Oi, alguém vai dar lance?"}))

            received = await _await_chat(ws_b)
            message = received.get("message") or {}
            checker.equal("Mensagem chega ao outro participante", message.get("text"), "Oi, alguém vai dar lance?")
            checker.equal("Mensagem identifica o autor", message.get("user_id"), user_a.id)
            checker.ok("Mensagem não expõe e-mail", "email" not in message)
            checker.ok(
                "Mensagem usa nome mascarado",
                message.get("display_name") != user_a.display_name,
            )

            # O próprio autor também recebe o eco (broadcast para a sala toda).
            own = await _await_chat(ws_a)
            checker.equal("Autor recebe o eco", (own.get("message") or {}).get("text"), "Oi, alguém vai dar lance?")

            # Com a sala ainda ocupada, o histórico fica visível na sala REST.
            response = await client.get(
                f"/api/auctions/{auction['id']}/room",
                headers=auth_headers(user_b),
            )
            checker.equal("Sala REST -> 200", response.status_code, 200)
            if response.status_code == 200:
                room = response.json()
                checker.equal("Histórico do chat presente na sala", len(room.get("chat", [])), 1)
                checker.equal(
                    "Histórico guarda o texto",
                    room["chat"][0].get("text"),
                    "Oi, alguém vai dar lance?",
                )
        finally:
            await ws_a.close()
            await ws_b.close()

    return checker.finish()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
