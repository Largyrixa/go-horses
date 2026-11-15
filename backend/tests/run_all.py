#!/usr/bin/env python3
"""Executa toda a suíte de testes de caixa-preta do Go Horses.

Ordem:
  1. autenticação/autorização;
  2. SQL injection;
  3. corridas de leilão;
  4. benchmark (opcional, só leitura).

Cada script é executado em um subprocesso com o mesmo Python; o código de saída
agregado é 0 somente se todos passarem. O benchmark não falha por latência, a
menos que --max-p95-ms seja informado (use `make bench` diretamente para isso).
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

from common import build_parser, ensure_api, make_client

TEST_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TEST_DIR.parent
TEST_SCRIPTS = (
    "test_auth.py",
    "test_sql_injection.py",
    "test_race_auction.py",
    "test_features.py",
    "test_chat.py",
)


async def preflight(base_url: str) -> bool:
    async with make_client(base_url, timeout=10.0) as client:
        return await ensure_api(client)


def run_script(script: str, args: list[str], base_url: str) -> tuple[int, float]:
    command = [sys.executable, str(TEST_DIR / script), *args]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=str(BACKEND_DIR),
            env={**os.environ, "GOHORSES_API": base_url},
            timeout=900,
        )
        elapsed = time.perf_counter() - started
        return completed.returncode, elapsed
    except subprocess.TimeoutExpired:
        elapsed = time.perf_counter() - started
        print(f"ERRO: {script} excedeu o limite de 900s.", file=sys.stderr)
        return 124, elapsed


def main() -> int:
    parser = build_parser("Suíte de testes de caixa-preta do Go Horses")
    parser.add_argument(
        "--skip-benchmark",
        action="store_true",
        help="não executa o benchmark ao final",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="benchmark reduzido (80 requisições, concorrência 10)",
    )
    parser.add_argument("--bench-requests", type=int, default=300)
    parser.add_argument("--bench-concurrency", type=int, default=20)
    args = parser.parse_args()

    print(f"Go Horses - suíte de testes em {args.base_url}", flush=True)
    if not asyncio.run(preflight(args.base_url)):
        return 2

    common_args = ["--base-url", args.base_url]
    results: list[tuple[str, int, float]] = []

    for script in TEST_SCRIPTS:
        print(f"\n{'=' * 78}")
        print(f"Executando {script}")
        print(f"{'=' * 78}", flush=True)
        code, elapsed = run_script(script, common_args, args.base_url)
        results.append((script, code, elapsed))

    if not args.skip_benchmark:
        print(f"\n{'=' * 78}")
        print("Executando benchmark.py")
        print(f"{'=' * 78}", flush=True)
        benchmark_args = [*common_args]
        if args.quick:
            benchmark_args += ["--requests", "80", "--concurrency", "10", "--warmup", "5"]
        else:
            benchmark_args += [
                "--requests",
                str(args.bench_requests),
                "--concurrency",
                str(args.bench_concurrency),
            ]
        code, elapsed = run_script("benchmark.py", benchmark_args, args.base_url)
        results.append(("benchmark.py", code, elapsed))

    print(f"\n{'=' * 78}")
    print("Resumo")
    print(f"{'=' * 78}")
    failed = False
    for name, code, elapsed in results:
        status = "OK" if code == 0 else f"FALHOU (exit {code})"
        if code != 0:
            failed = True
        print(f"  {name:<24} {status:<22} {elapsed:6.1f}s")

    print()
    if failed:
        print("Resultado: FALHOU")
        return 1
    print("Resultado: OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
