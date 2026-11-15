"""Utilitários compartilhados dos testes de caixa-preta do Go Horses.

Os scripts falam com a API por HTTP e não importam o código da aplicação.
Dependência: httpx (já presente em backend/requirements.txt).
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from urllib.parse import quote, urlencode, urlsplit

try:
    import httpx
except ModuleNotFoundError:
    raise SystemExit(
        "httpx não encontrado. Rode com o Python da venv do backend:\n"
        "  cd backend && .venv/bin/python tests/<script>.py"
    )

DEFAULT_BASE_URL = os.getenv("GOHORSES_API", "http://127.0.0.1:8088").rstrip("/")
TEST_PASSWORD = (
    os.getenv("GOHORSES_PASSWORD")
    or os.getenv("SEED_PASSWORD")
    or "senha1234"
)
TEST_EMAIL_DOMAIN = "go-horses.dev"
PHOTOS = [f"/static/demo/bike-{index}.svg" for index in range(1, 4)]

# Marcadores que indicam vazamento de detalhes internos em uma resposta.
LEAK_MARKERS = (
    "Traceback (most recent call last)",
    "psycopg",
    "sqlstate",
    "PrismaClient",
    "prisma.errors",
    'File "/',
    "OperationalError",
)


@dataclass
class TestUser:
    id: str
    email: str
    display_name: str
    token: str


@dataclass
class Checker:
    """Contador simples de verificações, sem depender de pytest."""

    suite: str
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    failures: list[str] = field(default_factory=list)

    def ok(self, name: str, condition: bool, detail: str = "") -> bool:
        if condition:
            self.passed += 1
            print(f"[OK]     {name}")
            return True
        self.failed += 1
        message = f"{name}{': ' + detail if detail else ''}"
        self.failures.append(message)
        print(f"[FALHOU] {message}")
        return False

    def equal(self, name: str, actual: Any, expected: Any) -> bool:
        return self.ok(
            name,
            actual == expected,
            f"esperado={expected!r}, obtido={actual!r}",
        )

    def is_in(self, name: str, actual: Any, expected: Sequence[Any]) -> bool:
        return self.ok(
            name,
            actual in expected,
            f"esperado um de {tuple(expected)!r}, obtido={actual!r}",
        )

    def skip(self, name: str, reason: str) -> None:
        self.skipped += 1
        print(f"[PULADO] {name}: {reason}")

    def finish(self) -> int:
        total = self.passed + self.failed
        print()
        print(
            f"== {self.suite}: {self.passed}/{total} verificações passaram, "
            f"{self.failed} falharam, {self.skipped} puladas =="
        )
        if self.failures:
            print("Falhas:")
            for failure in self.failures:
                print(f"  - {failure}")
        return 0 if self.failed == 0 else 1


def build_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"URL da API (padrão: {DEFAULT_BASE_URL} ou $GOHORSES_API)",
    )
    return parser


def make_client(
    base_url: str,
    *,
    concurrency: int = 20,
    timeout: float = 30.0,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=timeout,
        limits=httpx.Limits(
            max_connections=max(20, concurrency + 10),
            max_keepalive_connections=max(10, concurrency),
        ),
        headers={"User-Agent": "gohorses-tests/1.0"},
    )


async def ensure_api(client: httpx.AsyncClient) -> bool:
    """Confere se a API está no ar antes de começar a suíte."""
    base_url = str(client.base_url).rstrip("/")
    try:
        response = await client.get("/api/health")
    except httpx.HTTPError as exc:
        print(f"ERRO: API não respondeu em {base_url}: {exc}", file=sys.stderr)
        print("Suba a API com `make api` ou passe --base-url.", file=sys.stderr)
        return False

    if response.status_code != 200:
        print(
            f"ERRO: GET /api/health respondeu {response.status_code}: "
            f"{preview(response)}",
            file=sys.stderr,
        )
        return False

    try:
        data = response.json()
    except ValueError:
        data = {}
    if data.get("status") != "ok":
        print(f"ERRO: /api/health inesperado: {preview(response)}", file=sys.stderr)
        return False
    return True


def auth_headers(user: TestUser) -> dict[str, str]:
    return {"Authorization": f"Bearer {user.token}"}


async def login(client: httpx.AsyncClient, email: str, password: str = TEST_PASSWORD) -> str:
    response = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Falha no login de {email}: {response.status_code} {preview(response)}"
        )
    return response.json()["token"]


async def register_user(
    client: httpx.AsyncClient,
    prefix: str = "user",
    *,
    display_name: str | None = None,
) -> TestUser:
    suffix = uuid.uuid4().hex[:12]
    email = f"teste+{prefix}-{suffix}@{TEST_EMAIL_DOMAIN}"
    name = display_name or f"Teste {prefix} {suffix}"
    response = await client.post(
        "/api/auth/register",
        json={
            "display_name": name,
            "email": email,
            "password": TEST_PASSWORD,
            "monthly_income_cents": 1_000_000,
        },
    )
    if response.status_code != 201:
        raise RuntimeError(
            f"Falha ao registrar {email}: {response.status_code} {preview(response)}"
        )
    token = await login(client, email)
    return TestUser(
        id=response.json()["id"],
        email=email,
        display_name=name,
        token=token,
    )


def iso_utc(seconds_from_now: float = 0) -> str:
    moment = datetime.now(timezone.utc) + timedelta(seconds=seconds_from_now)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def create_auction(
    client: httpx.AsyncClient,
    seller: TestUser,
    *,
    name: str | None = None,
    description: str | None = None,
    category: str = "Outros",
    starts_in: int = 0,
    duration: int = 300,
    starting_price: int = 10_000,
) -> dict[str, Any]:
    payload = {
        "name": name or f"Leilão de teste {uuid.uuid4().hex[:8]}",
        "description": description or "Leilão criado pela suíte de testes.",
        "category": category,
        "photos": PHOTOS,
        "starting_price": starting_price,
        "starts_at": iso_utc(starts_in),
        "duration_seconds": duration,
    }
    response = await client.post(
        "/api/auctions",
        headers=auth_headers(seller),
        json=payload,
    )
    if response.status_code != 201:
        raise RuntimeError(
            f"Falha ao criar leilão: {response.status_code} {preview(response)}"
        )
    return response.json()


async def auction_detail(
    client: httpx.AsyncClient, auction_id: str
) -> dict[str, Any]:
    response = await client.get(f"/api/auctions/{quote(auction_id, safe='')}")
    if response.status_code != 200:
        raise RuntimeError(
            f"Falha ao consultar leilão {auction_id}: "
            f"{response.status_code} {preview(response)}"
        )
    return response.json()


async def place_bid(
    client: httpx.AsyncClient,
    user: TestUser,
    auction_id: str,
    amount: int,
    idempotency_key: str,
) -> httpx.Response:
    return await client.post(
        f"/api/auctions/{quote(auction_id, safe='')}/bids",
        headers={
            **auth_headers(user),
            "Idempotency-Key": idempotency_key,
        },
        json={"amount": int(amount)},
    )


def error_code(response: httpx.Response) -> str | None:
    try:
        return response.json().get("error", {}).get("code")
    except (ValueError, AttributeError):
        return None


def preview(response: httpx.Response, limit: int = 300) -> str:
    text = response.text.replace("\n", " ").replace("\r", " ")
    return text[:limit] + ("..." if len(text) > limit else "")


def looks_like_internal_leak(text: str) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in LEAK_MARKERS)


def path_from_public_url(url: str) -> str:
    """Extrai caminho + query de uma URL absoluta devolvida pela API.

    Assim o teste sempre bate no --base-url, mesmo que PUBLIC_BASE_URL aponte
    para outro host.
    """
    parsed = urlsplit(url)
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


def websocket_url(
    base_url: str,
    auction_id: str,
    *,
    token: str | None = None,
    role: str = "spectator",
) -> str:
    if base_url.startswith("https://"):
        base = "wss://" + base_url[len("https://") :]
    elif base_url.startswith("http://"):
        base = "ws://" + base_url[len("http://") :]
    else:
        base = base_url.rstrip("/")
    params: dict[str, str] = {"role": role}
    if token:
        params["token"] = token
    return f"{base}/api/auctions/{quote(auction_id, safe='')}/ws?{urlencode(params)}"


def percentile(values: Sequence[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((percent / 100.0) * (len(ordered) - 1)))
    index = max(0, min(len(ordered) - 1, index))
    return ordered[index]


def format_ms(value: float) -> str:
    if value >= 1000:
        return f"{value / 1000:.2f}s"
    return f"{value:.1f}ms"
