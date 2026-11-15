#!/usr/bin/env python3
"""Benchmark HTTP do Go Horses (latência, percentis e throughput).

Por padrão mede apenas rotas de leitura. O login é feito uma vez para medir a
sala autenticada; use --include-login para incluir o POST /api/auth/login no
benchmark (ele executa scrypt e é naturalmente mais caro).

Exemplos:
    .venv/bin/python tests/benchmark.py
    .venv/bin/python tests/benchmark.py --requests 1000 --concurrency 50
    .venv/bin/python tests/benchmark.py --json resultado.json --max-p95-ms 250
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass

from common import (
    build_parser,
    ensure_api,
    format_ms,
    make_client,
    percentile,
    preview,
)

DEFAULT_EMAIL = os.getenv("GOHORSES_EMAIL", "bruno@go-horses.dev")
DEFAULT_PASSWORD = (
    os.getenv("GOHORSES_PASSWORD")
    or os.getenv("SEED_PASSWORD")
    or "senha1234"
)


@dataclass
class BenchmarkResult:
    endpoint: str
    requests: int
    errors: int
    rps: float
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    statuses: dict[int, int]


async def _one_request(client, method, path, headers, json_body):
    started = time.perf_counter()
    try:
        response = await client.request(
            method,
            path,
            headers=headers,
            json=json_body,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        return elapsed_ms, response.status_code, None, response
    except Exception as exc:  # noqa: BLE001 - erro de transporte entra no relatório
        elapsed_ms = (time.perf_counter() - started) * 1000
        return elapsed_ms, None, repr(exc), None


async def run_endpoint(
    client,
    name: str,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict | None = None,
    total: int,
    concurrency: int,
    warmup: int,
) -> BenchmarkResult:
    if total < 1:
        total = 1

    async def one():
        return await _one_request(client, method, path, headers, json_body)

    # Aquecimento: conexão TCP/TLS + caches do servidor.
    for _ in range(min(warmup, total)):
        await one()

    latencies: list[float] = []
    statuses: Counter[int] = Counter()
    errors: list[str] = []
    counter = 0

    async def worker() -> None:
        nonlocal counter
        while True:
            if counter >= total:
                return
            counter += 1
            elapsed_ms, status, error, response = await one()
            latencies.append(elapsed_ms)
            if error is not None:
                errors.append(error)
                continue
            statuses[status] += 1
            if status >= 500:
                errors.append(
                    f"HTTP {status}: {preview(response)}" if response else f"HTTP {status}"
                )

    started = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    wall_seconds = time.perf_counter() - started

    return BenchmarkResult(
        endpoint=name,
        requests=total,
        errors=len(errors),
        rps=total / wall_seconds if wall_seconds > 0 else 0.0,
        p50_ms=percentile(latencies, 50),
        p90_ms=percentile(latencies, 90),
        p95_ms=percentile(latencies, 95),
        p99_ms=percentile(latencies, 99),
        max_ms=max(latencies) if latencies else 0.0,
        statuses=dict(statuses),
    )


async def find_auction(client) -> str | None:
    for status in ("running", "scheduled", "sold", "unsold"):
        try:
            response = await client.get(
                "/api/auctions",
                params={"status": status, "page": 1},
            )
        except Exception:  # noqa: BLE001 - tentamos o próximo estado
            continue
        if response.status_code == 200:
            items = response.json().get("items", [])
            if items:
                return items[0]["id"]
    return None


async def try_login(client, email: str, password: str) -> str | None:
    try:
        response = await client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
    except Exception as exc:  # noqa: BLE001
        print(f"AVISO: login falhou ({exc}); rotas autenticadas serão puladas.")
        return None
    if response.status_code != 200:
        print(
            "AVISO: login de benchmark falhou "
            f"({response.status_code} {preview(response)}). "
            "Rode `make seed` ou passe --email/--password. "
            "Rotas autenticadas serão puladas."
        )
        return None
    return response.json()["token"]


def print_table(results: list[BenchmarkResult]) -> None:
    print()
    print(
        f"{'endpoint':<42} {'n':>6} {'erros':>6} {'rps':>9} "
        f"{'p50':>9} {'p90':>9} {'p95':>9} {'p99':>9} {'max':>9}"
    )
    print("-" * 115)
    for result in results:
        print(
            f"{result.endpoint:<42} {result.requests:>6} {result.errors:>6} "
            f"{result.rps:>9.1f} "
            f"{format_ms(result.p50_ms):>9} "
            f"{format_ms(result.p90_ms):>9} "
            f"{format_ms(result.p95_ms):>9} "
            f"{format_ms(result.p99_ms):>9} "
            f"{format_ms(result.max_ms):>9}"
        )
        if any(status >= 400 for status in result.statuses):
            print(f"  status: {result.statuses}")


async def main() -> int:
    parser = build_parser("Benchmark HTTP do Go Horses")
    parser.add_argument(
        "--requests",
        type=int,
        default=300,
        help="requisições por endpoint (padrão: 300)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=20,
        help="requisições simultâneas (padrão: 20)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=20,
        help="requisições de aquecimento por endpoint (padrão: 20)",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        help="salva os resultados em um arquivo JSON",
    )
    parser.add_argument(
        "--max-p95-ms",
        type=float,
        help="falha se o p95 de qualquer endpoint ultrapassar este valor",
    )
    parser.add_argument(
        "--include-login",
        action="store_true",
        help="inclui POST /api/auth/login no benchmark",
    )
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    args = parser.parse_args()

    if args.requests < 1:
        parser.error("--requests deve ser pelo menos 1")
    if args.concurrency < 1:
        parser.error("--concurrency deve ser pelo menos 1")
    if args.warmup < 0:
        parser.error("--warmup não pode ser negativo")

    async with make_client(
        args.base_url, concurrency=args.concurrency, timeout=60.0
    ) as client:
        if not await ensure_api(client):
            return 2

        print(f"Benchmark em {args.base_url}")
        print(
            f"requests={args.requests} por endpoint, "
            f"concurrency={args.concurrency}, warmup={args.warmup}"
        )

        token = await try_login(client, args.email, args.password)
        auction_id = await find_auction(client)
        if auction_id is None:
            print("AVISO: nenhum leilão encontrado; detalhe/sala serão pulados.")

        endpoints: list[tuple[str, str, str, dict | None, dict | None]] = [
            ("GET /api/health", "GET", "/api/health", None, None),
            ("GET /api/categories", "GET", "/api/categories", None, None),
            ("GET /api/auctions", "GET", "/api/auctions?page=1", None, None),
        ]
        if auction_id:
            endpoints.append(
                (
                    "GET /api/auctions/{id}",
                    "GET",
                    f"/api/auctions/{auction_id}",
                    None,
                    None,
                )
            )
        if token and auction_id:
            endpoints.append(
                (
                    "GET /api/auctions/{id}/room",
                    "GET",
                    f"/api/auctions/{auction_id}/room",
                    {"Authorization": f"Bearer {token}"},
                    None,
                )
            )
        if args.include_login and token:
            endpoints.append(
                (
                    "POST /api/auth/login",
                    "POST",
                    "/api/auth/login",
                    None,
                    {"email": args.email, "password": args.password},
                )
            )

        results: list[BenchmarkResult] = []
        for name, method, path, headers, json_body in endpoints:
            print(f"  medindo {name} ...", flush=True)
            result = await run_endpoint(
                client,
                name,
                method,
                path,
                headers=headers,
                json_body=json_body,
                total=args.requests,
                concurrency=args.concurrency,
                warmup=args.warmup,
            )
            results.append(result)

    print_table(results)

    payload = [asdict(result) for result in results]
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        print(f"\nResultados salvos em {args.json_path}")

    failures: list[str] = []
    for result in results:
        if result.errors:
            failures.append(
                f"{result.endpoint}: {result.errors} erro(s) de transporte/5xx"
            )
        if args.max_p95_ms is not None and result.p95_ms > args.max_p95_ms:
            failures.append(
                f"{result.endpoint}: p95 {format_ms(result.p95_ms)} > "
                f"{format_ms(args.max_p95_ms)}"
            )

    if failures:
        print("\nFalhas do benchmark:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
