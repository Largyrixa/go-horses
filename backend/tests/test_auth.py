#!/usr/bin/env python3
"""Testes de autenticação e autorização do Go Horses (caixa-preta).

Cobre:
  - ações protegidas chamadas sem token, com token inválido e com token via query;
  - logout invalidando a sessão;
  - autorização entre usuários (cancelamento, lance do comitente, IDOR);
  - perfil público sem e-mail;
  - uploads: presign autenticado, token adulterado, chave trocada e content-type;
  - WebSocket sem token / com token inválido / autenticado.
"""
from __future__ import annotations

import asyncio
import json
import sys
from urllib.parse import quote

from common import (
    Checker,
    auth_headers,
    build_parser,
    create_auction,
    error_code,
    ensure_api,
    looks_like_internal_leak,
    make_client,
    path_from_public_url,
    place_bid,
    preview,
    register_user,
    websocket_url,
)


PROTECTED_ENDPOINTS = (
    ("GET", "/api/auth/me", None, "sem token"),
    ("POST", "/api/auth/logout", None, "sem token"),
    ("GET", "/api/me/auctions", None, "sem token"),
    ("GET", "/api/me/participations", None, "sem token"),
    ("POST", "/api/auctions", "auction_body", "sem token"),
    ("POST", "/api/auctions/{scheduled}/cancel", None, "sem token"),
    ("GET", "/api/auctions/{running}/room", None, "sem token"),
    ("POST", "/api/auctions/{running}/bids", "bid_body", "sem token"),
    ("POST", "/api/uploads/presign", "presign_body", "sem token"),
)


async def _ws_close_code(url: str) -> int | None:
    import websockets

    try:
        async with websockets.connect(url, open_timeout=5) as websocket:
            try:
                await asyncio.wait_for(websocket.recv(), timeout=5)
            except websockets.exceptions.ConnectionClosed as exc:
                return exc.code
            return None
    except websockets.exceptions.ConnectionClosed as exc:
        return exc.code


async def check_websocket(
    checker: Checker,
    base_url: str,
    auction_id: str,
    user,
) -> None:
    try:
        import websockets  # noqa: F401
    except ModuleNotFoundError:
        checker.skip("WebSocket", "pacote `websockets` não instalado")
        return

    print("\n-- WebSocket --")
    try:
        code = await _ws_close_code(websocket_url(base_url, auction_id))
        checker.equal("WS sem token fecha com 4401", code, 4401)

        code = await _ws_close_code(
            websocket_url(base_url, auction_id, token="token-invalido")
        )
        checker.equal("WS com token inválido fecha com 4401", code, 4401)

        async with websockets.connect(
            websocket_url(
                base_url,
                auction_id,
                token=user.token,
                role="spectator",
            ),
            open_timeout=5,
        ) as websocket:
            raw = await asyncio.wait_for(websocket.recv(), timeout=5)
            state = json.loads(raw)
            checker.equal(
                "WS autenticado recebe o estado do leilão",
                state.get("auction", {}).get("id"),
                auction_id,
            )
    except Exception as exc:  # noqa: BLE001 - falha do teste deve ser reportada
        checker.ok("WebSocket", False, repr(exc))


async def main() -> int:
    args = build_parser(
        "Testes de autenticação e autorização do Go Horses"
    ).parse_args()
    checker = Checker("Autenticação e autorização")

    async with make_client(args.base_url) as client:
        if not await ensure_api(client):
            return 2

        print("-- Preparando usuários e leilões --")
        seller = await register_user(client, "auth-seller")
        buyer = await register_user(client, "auth-buyer")
        other = await register_user(client, "auth-other")

        scheduled = await create_auction(
            client,
            seller,
            name="Leilão protegido (agendado)",
            starts_in=900,
            duration=600,
        )
        running = await create_auction(
            client,
            seller,
            name="Leilão protegido (em andamento)",
            starts_in=0,
            duration=300,
        )
        min_bid = running["min_bid"]

        auction_body = {
            "name": "Tentativa sem autenticação",
            "description": "Não deve ser criado.",
            "category": "Outros",
            "photos": [
                "/static/demo/bike-1.svg",
                "/static/demo/bike-2.svg",
                "/static/demo/bike-3.svg",
            ],
            "starting_price": 1_000,
            "starts_at": "2030-01-01T00:00:00Z",
            "duration_seconds": 300,
        }
        bid_body = {"amount": min_bid}
        presign_body = {
            "filename": "sem-auth.png",
            "content_type": "image/png",
            "size": 10,
        }

        print("\n-- Ações protegidas sem autenticação --")
        for method, path_template, body_name, label in PROTECTED_ENDPOINTS:
            path = path_template.format(
                scheduled=scheduled["id"],
                running=running["id"],
            )
            body = {
                "auction_body": auction_body,
                "bid_body": bid_body,
                "presign_body": presign_body,
            }.get(body_name)
            headers = {"Idempotency-Key": "sem-auth"} if body_name == "bid_body" else {}

            response = await client.request(
                method,
                path,
                json=body,
                headers=headers,
            )
            endpoint = f"{method} {path_template.format(scheduled='{id}', running='{id}')}"
            checker.equal(f"{endpoint} {label} -> 401", response.status_code, 401)
            if response.status_code == 401:
                checker.equal(
                    f"{endpoint} {label} retorna código unauthorized",
                    error_code(response),
                    "unauthorized",
                )
            else:
                print(f"         resposta: {preview(response)}")
            checker.ok(
                f"{endpoint} {label} não vaza detalhes internos",
                not looks_like_internal_leak(response.text),
            )

        print("\n-- Tokens inválidos e formato do header --")
        invalid_headers = (
            ("token inexistente", {"Authorization": "Bearer token-que-nao-existe"}),
            ("esquema Basic", {"Authorization": "Basic dXNlcjpzZW5oYQ=="}),
            ("Bearer sem credenciais", {"Authorization": "Bearer"}),
            ("token aleatório longo", {"Authorization": "Bearer " + "a" * 128}),
        )
        for label, headers in invalid_headers:
            response = await client.get("/api/auth/me", headers=headers)
            checker.equal(f"GET /api/auth/me com {label} -> 401", response.status_code, 401)

        response = await client.get(f"/api/auth/me?token={quote(seller.token)}")
        checker.equal(
            "Token na query string não autentica rotas REST",
            response.status_code,
            401,
        )

        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"bearer {seller.token}"},
        )
        checker.equal(
            "Esquema bearer minúsculo continua válido",
            response.status_code,
            200,
        )

        print("\n-- Logout invalida a sessão --")
        temporary = await register_user(client, "auth-logout")
        response = await client.get("/api/auth/me", headers=auth_headers(temporary))
        checker.equal("Sessão recém-criada funciona", response.status_code, 200)
        response = await client.post("/api/auth/logout", headers=auth_headers(temporary))
        checker.equal("Logout autenticado -> 204", response.status_code, 204)
        response = await client.get("/api/auth/me", headers=auth_headers(temporary))
        checker.equal("Token antigo após logout -> 401", response.status_code, 401)

        print("\n-- Autorização entre usuários --")
        response = await client.post(
            f"/api/auctions/{scheduled['id']}/cancel",
            headers=auth_headers(buyer),
        )
        checker.equal("Comprador cancela leilão de outro -> 403", response.status_code, 403)
        checker.equal("Cancelamento indevido retorna not_seller", error_code(response), "not_seller")

        response = await client.post(
            f"/api/auctions/{scheduled['id']}/cancel",
            headers=auth_headers(seller),
        )
        checker.equal("Comitente cancela o próprio leilão agendado -> 200", response.status_code, 200)
        checker.equal(
            "Leilão fica com status cancelled",
            response.json().get("status"),
            "cancelled",
        )
        response = await client.post(
            f"/api/auctions/{scheduled['id']}/cancel",
            headers=auth_headers(seller),
        )
        checker.equal("Cancelar novamente -> 409", response.status_code, 409)
        checker.equal("Segundo cancelamento retorna already_cancelled", error_code(response), "already_cancelled")

        response = await place_bid(
            client,
            seller,
            running["id"],
            min_bid,
            "seller-nao-pode-dar-lance",
        )
        checker.equal("Comitente dá lance no próprio leilão -> 403", response.status_code, 403)
        checker.equal("Lance do comitente retorna seller_cannot_bid", error_code(response), "seller_cannot_bid")

        response = await place_bid(
            client,
            buyer,
            running["id"],
            min_bid,
            "buyer-primeiro-lance",
        )
        checker.equal("Comprador dá lance válido -> 201", response.status_code, 201)

        response = await client.post(
            f"/api/auctions/{running['id']}/cancel",
            headers=auth_headers(seller),
        )
        checker.equal("Cancelar leilão em andamento com lances -> 409", response.status_code, 409)
        checker.equal("Cancelamento com lances retorna has_bids", error_code(response), "has_bids")

        response = await client.get("/api/me/auctions", headers=auth_headers(buyer))
        buyer_auctions = {item["id"] for item in response.json().get("items", [])}
        checker.ok(
            "GET /api/me/auctions não vaza leilões de outro usuário",
            running["id"] not in buyer_auctions and scheduled["id"] not in buyer_auctions,
        )

        response = await client.get("/api/me/participations", headers=auth_headers(other))
        participations = {
            item["auction"]["id"] for item in response.json().get("items", [])
        }
        checker.ok(
            "GET /api/me/participations não vaza participação alheia",
            running["id"] not in participations,
        )

        print("\n-- Perfil público e rotas públicas --")
        response = await client.get(f"/api/users/{seller.id}")
        checker.equal("Perfil público do comitente -> 200", response.status_code, 200)
        checker.ok("Perfil público não expõe e-mail", "email" not in response.json())

        response = await client.get("/api/users/nao-existe")
        checker.equal("Perfil público inexistente -> 404", response.status_code, 404)
        checker.equal("Perfil inexistente retorna user_not_found", error_code(response), "user_not_found")

        for path in ("/api/auctions", "/api/categories", f"/api/auctions/{running['id']}"):
            response = await client.get(path)
            checker.equal(f"Rota pública {path} funciona sem token", response.status_code, 200)

        response = await client.get(
            f"/api/auctions/{running['id']}/room",
            headers=auth_headers(buyer),
        )
        checker.equal("Sala com token válido -> 200", response.status_code, 200)

        print("\n-- Uploads --")
        file_bytes = b"\x89PNG\r\n\x1a\n" + b"gohorses-test"
        payload = {
            "filename": "teste.png",
            "content_type": "image/png",
            "size": len(file_bytes),
        }
        response = await client.post(
            "/api/uploads/presign",
            headers=auth_headers(seller),
            json=payload,
        )
        checker.equal("Presign autenticado -> 200", response.status_code, 200)
        if response.status_code == 200:
            presign = response.json()
            upload_path = path_from_public_url(presign["upload_url"])
            public_path = path_from_public_url(presign["public_url"])

            response = await client.put(
                upload_path.split("?", 1)[0],
                content=file_bytes,
                headers={"Content-Type": "image/png"},
            )
            checker.is_in("PUT sem token -> 401/403/422", response.status_code, (401, 403, 422))

            tampered_path = upload_path[:-1] + (
                "A" if upload_path[-1] != "A" else "B"
            )
            response = await client.put(
                tampered_path,
                content=file_bytes,
                headers={"Content-Type": "image/png"},
            )
            checker.equal("PUT com token adulterado -> 403", response.status_code, 403)

            key_path, _, query = upload_path.partition("?")
            changed_key_path = key_path.rsplit("/", 1)[0] + "/outra-chave.png?" + query
            response = await client.put(
                changed_key_path,
                content=file_bytes,
                headers={"Content-Type": "image/png"},
            )
            checker.equal("PUT com chave trocada -> 403", response.status_code, 403)

            response = await client.put(
                upload_path,
                content=file_bytes,
                headers={"Content-Type": "text/plain"},
            )
            checker.equal("PUT com content-type errado -> 415", response.status_code, 415)

            response = await client.put(
                upload_path,
                content=file_bytes + b"x",
                headers={"Content-Type": "image/png"},
            )
            checker.equal("PUT maior que o declarado -> 413", response.status_code, 413)

            response = await client.put(
                upload_path,
                content=file_bytes,
                headers={"Content-Type": "image/png"},
            )
            checker.equal("PUT válido -> 204", response.status_code, 204)

            response = await client.get(public_path)
            checker.equal("GET da URL pública do upload -> 200", response.status_code, 200)
            checker.equal("Conteúdo público confere", response.content, file_bytes)

        await check_websocket(checker, args.base_url, running["id"], buyer)

    return checker.finish()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
