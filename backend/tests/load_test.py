#!/usr/bin/env python3
"""Teste de carga/capacidade do Go Horses.

Descobre quantos usuários simultâneos o servidor sustenta dentro de um SLA
(latência p95 e taxa de erro). Modos:

  http  - N usuários fazendo ciclos de listagem + detalhe + sala;
  ws    - N conexões WebSocket simultâneas na sala de um leilão;
  both  - executa a rampa HTTP e depois a rampa WebSocket.

O script faz uma rampa (padrão: 10, 25, 50, 100 usuários) e para no primeiro
nível que falhar, salvo --keep-going. A "capacidade" é o maior nível que passou
no SLA. Use --json para salvar os resultados.

AVISO: é um teste de carga agressivo. Rode apenas em ambiente autorizado.
Para cargas altas, use uma máquina cliente separada: o próprio cliente pode
ser o gargalo (CPU, descritores, rede).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

try:
    import websockets
except ModuleNotFoundError:  # uvicorn[standard] já instala, mas deixamos claro
    websockets = None

try:
    import resource
except ModuleNotFoundError:  # pragma: no cover - não é o alvo do projeto
    resource = None

from common import (
    TestUser,
    auth_headers,
    build_parser,
    create_auction,
    ensure_api,
    format_ms,
    login,
    make_client,
    percentile,
    register_user,
    websocket_url,
)

DEFAULT_EMAIL = os.getenv("GOHORSES_EMAIL", "bruno@go-horses.dev")
DEFAULT_PASSWORD = (
    os.getenv("GOHORSES_PASSWORD")
    or os.getenv("SEED_PASSWORD")
    or "senha1234"
)


@dataclass
class ProcessSample:
    ticks: int | None = None
    rss_mb: float | None = None


@dataclass
class HttpStep:
    users: int
    duration_s: float
    requests: int
    cycles: int
    errors: int
    statuses: dict[int, int]
    rps: float
    cycles_per_s: float
    error_rate: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    cpu_percent: float | None
    rss_mb: float | None
    passed: bool


@dataclass
class WsStep:
    users: int
    connected: int
    failed: int
    early_closes: int
    messages: int
    connect_p50_ms: float
    connect_p95_ms: float
    connect_p99_ms: float
    first_p95_ms: float
    error_rate: float
    cpu_percent: float | None
    rss_mb: float | None
    errors_sample: list[str] = field(default_factory=list)
    passed: bool = False


def parse_users(value: str) -> list[int]:
    levels: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            level = int(part)
        except ValueError as exc:
            raise ValueError(f"nível inválido em --users: {part!r}") from exc
        if level < 1:
            raise ValueError("--users deve conter apenas inteiros positivos")
        levels.append(level)
    if not levels:
        raise ValueError("--users precisa de pelo menos um nível")
    return sorted(set(levels))


def read_process_sample(pid: int | None) -> ProcessSample:
    if pid is None:
        return ProcessSample()
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().split()
        ticks = int(fields[13]) + int(fields[14])
        status = Path(f"/proc/{pid}/status").read_text()
        rss_kb: int | None = None
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                rss_kb = int(line.split()[1])
                break
        return ProcessSample(
            ticks=ticks,
            rss_mb=(rss_kb / 1024.0) if rss_kb is not None else None,
        )
    except (OSError, ValueError, IndexError):
        return ProcessSample()


def process_cpu_percent(
    before: ProcessSample,
    after: ProcessSample,
    elapsed: float,
) -> float | None:
    if before.ticks is None or after.ticks is None or elapsed <= 0:
        return None
    try:
        hz = os.sysconf("SC_CLK_TCK")
    except (AttributeError, OSError, ValueError):
        return None
    return max(0.0, (after.ticks - before.ticks) / hz / elapsed * 100.0)


def check_fd_limit(users: int) -> None:
    if resource is None:
        return
    try:
        soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
    except (OSError, ValueError):
        return
    if soft != resource.RLIM_INFINITY and users + 64 > soft:
        print(
            f"AVISO: ulimit -n={soft}; {users} conexões podem esgotar os "
            "descritores do cliente. Aumente o limite ou use outra máquina.",
            file=sys.stderr,
        )


async def ensure_auth(
    client: httpx.AsyncClient, email: str, password: str
) -> TestUser | None:
    try:
        token = await login(client, email, password)
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code == 200:
            data = response.json()
            return TestUser(
                id=data["id"],
                email=email,
                display_name=data.get("display_name", email),
                token=token,
            )
        print(
            f"AVISO: GET /api/auth/me respondeu {response.status_code}; "
            "tentando criar usuário de carga.",
            file=sys.stderr,
        )
    except Exception as exc:  # noqa: BLE001 - fallback para usuário novo
        print(f"AVISO: login de {email} falhou: {exc}", file=sys.stderr)

    print("Criando usuário de carga para as rotas autenticadas...", file=sys.stderr)
    try:
        return await register_user(client, "load")
    except Exception as exc:  # noqa: BLE001
        print(f"ERRO: não foi possível criar usuário de carga: {exc}", file=sys.stderr)
        return None


async def find_running_auction(client: httpx.AsyncClient) -> str | None:
    try:
        response = await client.get(
            "/api/auctions",
            params={"status": "running", "page": 1},
        )
    except httpx.HTTPError:
        return None
    if response.status_code == 200:
        items = response.json().get("items", [])
        if items:
            return items[0]["id"]
    return None


async def ensure_auction(
    client: httpx.AsyncClient,
    user: TestUser | None,
    auction_id: str | None,
    *,
    force_create: bool = False,
) -> str | None:
    if auction_id:
        return auction_id
    if not force_create:
        found = await find_running_auction(client)
        if found:
            return found
    if user is None:
        return None

    print("Criando leilão de carga (duração de 1 hora)...", file=sys.stderr)
    try:
        auction = await create_auction(
            client,
            user,
            name=f"Leilão de carga {time.time_ns()}",
            starts_in=0,
            duration=3600,
            starting_price=10_000,
        )
        return auction["id"]
    except Exception as exc:  # noqa: BLE001
        print(f"ERRO: não foi possível criar leilão de carga: {exc}", file=sys.stderr)
        return None


def http_scenario(
    auction_id: str | None,
    user: TestUser | None,
    include_room: bool,
) -> list[tuple[str, dict[str, str] | None]]:
    scenario: list[tuple[str, dict[str, str] | None]] = [
        ("/api/auctions?page=1", None),
    ]
    if auction_id:
        scenario.append((f"/api/auctions/{auction_id}", None))
        if include_room and user is not None:
            scenario.append(
                (
                    f"/api/auctions/{auction_id}/room",
                    auth_headers(user),
                )
            )
    return scenario


async def run_http_step(
    client: httpx.AsyncClient,
    *,
    users: int,
    duration: float,
    scenario: list[tuple[str, dict[str, str] | None]],
    sla_p95_ms: float,
    max_error_rate: float,
    server_pid: int | None,
) -> HttpStep:
    before = read_process_sample(server_pid)
    latencies: list[float] = []
    statuses: Counter[int] = Counter()
    errors = 0
    requests = 0
    cycles = 0
    started = time.perf_counter()
    stop_at = started + duration

    async def user_loop() -> None:
        nonlocal errors, requests, cycles
        while time.perf_counter() < stop_at:
            completed = True
            for path, headers in scenario:
                if time.perf_counter() >= stop_at:
                    completed = False
                    break
                request_started = time.perf_counter()
                try:
                    response = await client.get(path, headers=headers)
                except Exception:  # noqa: BLE001 - erro de transporte conta no SLA
                    errors += 1
                    requests += 1
                    completed = False
                    await asyncio.sleep(0.05)
                    break
                elapsed_ms = (time.perf_counter() - request_started) * 1000.0
                latencies.append(elapsed_ms)
                requests += 1
                statuses[response.status_code] += 1
                if response.status_code >= 400:
                    errors += 1
            if completed:
                cycles += 1

    try:
        await asyncio.gather(*(user_loop() for _ in range(users)))
    finally:
        elapsed = time.perf_counter() - started
        after = read_process_sample(server_pid)

    error_rate = (errors / requests) if requests else 1.0
    p95 = percentile(latencies, 95)
    passed = (
        requests > 0
        and error_rate <= max_error_rate
        and p95 <= sla_p95_ms
    )
    return HttpStep(
        users=users,
        duration_s=elapsed,
        requests=requests,
        cycles=cycles,
        errors=errors,
        statuses=dict(statuses),
        rps=(requests / elapsed) if elapsed > 0 else 0.0,
        cycles_per_s=(cycles / elapsed) if elapsed > 0 else 0.0,
        error_rate=error_rate,
        p50_ms=percentile(latencies, 50),
        p95_ms=p95,
        p99_ms=percentile(latencies, 99),
        max_ms=max(latencies) if latencies else 0.0,
        cpu_percent=process_cpu_percent(before, after, elapsed),
        rss_mb=after.rss_mb,
        passed=passed,
    )


async def run_ws_step(
    *,
    base_url: str,
    token: str,
    auction_id: str,
    users: int,
    hold: float,
    connect_concurrency: int,
    timeout: float,
    sla_p95_ms: float,
    max_error_rate: float,
    server_pid: int | None,
) -> WsStep:
    if websockets is None:
        raise RuntimeError("pacote websockets não instalado")

    before = read_process_sample(server_pid)
    url = websocket_url(
        base_url,
        auction_id,
        token=token,
        role="spectator",
    )
    started = time.perf_counter()
    semaphore = asyncio.Semaphore(max(1, connect_concurrency))

    async def reader(conn: dict[str, Any]) -> None:
        try:
            async for raw in conn["ws"]:
                conn["messages"] += 1
                if conn["first_event"].is_set():
                    continue
                try:
                    state = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                # O servidor também envia mensagens de contagem
                # (participants/spectators); a primeira mensagem de estado
                # precisa ter a chave "auction".
                if isinstance(state, dict) and "auction" in state:
                    conn["first_raw"] = raw
                    conn["first_ms"] = (
                        time.perf_counter() - conn["connected_at"]
                    ) * 1000.0
                    conn["first_event"].set()
        except Exception as exc:  # noqa: BLE001
            conn["reader_error"] = repr(exc)
        finally:
            conn["first_event"].set()

    async def connect_one() -> dict[str, Any]:
        conn: dict[str, Any] = {
            "ws": None,
            "connected_at": time.perf_counter(),
            "handshake_ms": None,
            "first_ms": None,
            "first_raw": None,
            "first_event": asyncio.Event(),
            "messages": 0,
            "error": None,
            "reader_error": None,
            "reader_task": None,
        }
        try:
            ws = await websockets.connect(
                url,
                open_timeout=timeout,
                close_timeout=timeout,
                max_size=2**20,
            )
            conn["ws"] = ws
            conn["handshake_ms"] = (
                time.perf_counter() - conn["connected_at"]
            ) * 1000.0
            conn["reader_task"] = asyncio.create_task(reader(conn))
            await asyncio.wait_for(conn["first_event"].wait(), timeout=timeout)
            if conn["first_raw"] is None:
                raise RuntimeError(
                    "conexão fechou antes da primeira mensagem"
                    + (
                        f" ({conn['reader_error']})"
                        if conn["reader_error"]
                        else ""
                    )
                )
            try:
                state = json.loads(conn["first_raw"])
                if not isinstance(state, dict) or "auction" not in state:
                    raise ValueError
            except (ValueError, TypeError):
                raise RuntimeError("primeira mensagem não é um estado de leilão")
        except Exception as exc:  # noqa: BLE001
            conn["error"] = repr(exc)
            if conn["ws"] is not None:
                try:
                    await asyncio.wait_for(
                        conn["ws"].close(), timeout=min(5.0, timeout)
                    )
                except Exception:  # noqa: BLE001
                    pass
            conn["ws"] = None
        return conn

    async def connect_limited() -> dict[str, Any]:
        async with semaphore:
            return await connect_one()

    connections = await asyncio.gather(
        *(connect_limited() for _ in range(users))
    )

    if hold > 0:
        await asyncio.sleep(hold)

    early_closes = 0
    for conn in connections:
        task = conn.get("reader_task")
        if conn["ws"] is not None and task is not None and task.done():
            early_closes += 1

    await asyncio.gather(
        *(
            asyncio.wait_for(
                conn["ws"].close(),
                timeout=min(5.0, timeout),
            )
            for conn in connections
            if conn["ws"] is not None
        ),
        return_exceptions=True,
    )
    await asyncio.gather(
        *(
            conn["reader_task"]
            for conn in connections
            if conn.get("reader_task") is not None
        ),
        return_exceptions=True,
    )

    elapsed = time.perf_counter() - started
    after = read_process_sample(server_pid)

    connected = sum(1 for conn in connections if conn["ws"] is not None)
    failed = users - connected
    reader_errors = sum(1 for conn in connections if conn["reader_error"])
    messages = sum(conn["messages"] for conn in connections)
    error_rate = min(
        1.0,
        (failed + early_closes + reader_errors) / users if users else 1.0,
    )

    connect_latencies = [
        conn["handshake_ms"]
        for conn in connections
        if conn["ws"] is not None and conn["handshake_ms"] is not None
    ]
    first_latencies = [
        conn["first_ms"]
        for conn in connections
        if conn["first_ms"] is not None
    ]
    connect_p95 = percentile(connect_latencies, 95)
    first_p95 = percentile(first_latencies, 95)
    passed = (
        connected > 0
        and error_rate <= max_error_rate
        and connect_p95 <= sla_p95_ms
        and first_p95 <= sla_p95_ms
    )

    errors_sample = [
        conn["error"] or conn["reader_error"]
        for conn in connections
        if conn["error"] or conn["reader_error"]
    ][:5]

    return WsStep(
        users=users,
        connected=connected,
        failed=failed,
        early_closes=early_closes,
        messages=messages,
        connect_p50_ms=percentile(connect_latencies, 50),
        connect_p95_ms=connect_p95,
        connect_p99_ms=percentile(connect_latencies, 99),
        first_p95_ms=first_p95,
        error_rate=error_rate,
        cpu_percent=process_cpu_percent(before, after, elapsed),
        rss_mb=after.rss_mb,
        errors_sample=errors_sample,
        passed=passed,
    )


def fmt_optional(value: float | None, digits: int = 1, suffix: str = "") -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}{suffix}"


def print_http_header() -> None:
    print()
    print(
        f"{'users':>6} {'reqs':>7} {'ciclos':>7} {'rps':>8} "
        f"{'p50':>8} {'p95':>8} {'p99':>8} {'max':>8} "
        f"{'erro%':>7} {'cpu%':>7} {'rss':>8}  resultado"
    )
    print("-" * 105)


def print_http_step(step: HttpStep) -> None:
    print(
        f"{step.users:>6} {step.requests:>7} {step.cycles:>7} "
        f"{step.rps:>8.1f} "
        f"{format_ms(step.p50_ms):>8} {format_ms(step.p95_ms):>8} "
        f"{format_ms(step.p99_ms):>8} {format_ms(step.max_ms):>8} "
        f"{step.error_rate * 100:>6.1f}% "
        f"{fmt_optional(step.cpu_percent, suffix='%'):>7} "
        f"{fmt_optional(step.rss_mb, suffix='MB'):>8}  "
        f"{'OK' if step.passed else 'FALHOU'}"
    )
    bad = {code: count for code, count in step.statuses.items() if code >= 400}
    if bad:
        print(f"       status HTTP: {bad}")


def print_ws_header() -> None:
    print()
    print(
        f"{'users':>6} {'ok':>5} {'fail':>5} {'early':>6} {'msgs':>8} "
        f"{'conn p50':>9} {'conn p95':>9} {'1a msg p95':>11} "
        f"{'erro%':>7} {'cpu%':>7} {'rss':>8}  resultado"
    )
    print("-" * 110)


def print_ws_step(step: WsStep) -> None:
    print(
        f"{step.users:>6} {step.connected:>5} {step.failed:>5} "
        f"{step.early_closes:>6} {step.messages:>8} "
        f"{format_ms(step.connect_p50_ms):>9} "
        f"{format_ms(step.connect_p95_ms):>9} "
        f"{format_ms(step.first_p95_ms):>11} "
        f"{step.error_rate * 100:>6.1f}% "
        f"{fmt_optional(step.cpu_percent, suffix='%'):>7} "
        f"{fmt_optional(step.rss_mb, suffix='MB'):>8}  "
        f"{'OK' if step.passed else 'FALHOU'}"
    )
    for error in step.errors_sample:
        print(f"       erro: {error}")


def capacity(results: list[HttpStep] | list[WsStep]) -> int | None:
    passed = [step.users for step in results if step.passed]
    return max(passed) if passed else None


def print_capacity(
    label: str,
    results: list[HttpStep] | list[WsStep],
    sla_p95_ms: float,
    max_error_rate: float,
) -> bool:
    if not results:
        return True
    value = capacity(results)
    if value is None:
        print(
            f"{label}: nenhum nível passou no SLA "
            f"(p95 <= {format_ms(sla_p95_ms)}, erros <= {max_error_rate * 100:.1f}%)."
        )
        return False
    print(
        f"{label}: até {value} usuários simultâneos dentro do SLA "
        f"(p95 <= {format_ms(sla_p95_ms)}, erros <= {max_error_rate * 100:.1f}%)."
    )
    return True


async def main() -> int:
    parser = build_parser("Teste de carga/capacidade do Go Horses")
    parser.add_argument(
        "--mode",
        choices=("http", "ws", "both"),
        default="http",
        help="tipo de carga (padrão: http)",
    )
    parser.add_argument(
        "--users",
        default="10,25,50,100",
        help="níveis de usuários simultâneos, separados por vírgula",
    )
    parser.add_argument(
        "--http-duration",
        type=float,
        default=15.0,
        help="duração de cada nível HTTP em segundos (padrão: 15)",
    )
    parser.add_argument(
        "--ws-hold",
        type=float,
        default=10.0,
        help="tempo mantendo as conexões WS abertas (padrão: 10s)",
    )
    parser.add_argument(
        "--ws-connect-concurrency",
        type=int,
        default=50,
        help="handshakes WS simultâneos por lote (padrão: 50)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="timeout por requisição/handshake em segundos (padrão: 15)",
    )
    parser.add_argument(
        "--sla-p95-ms",
        type=float,
        default=1000.0,
        help="p95 máximo aceitável em ms (padrão: 1000)",
    )
    parser.add_argument(
        "--max-error-rate",
        type=float,
        default=0.01,
        help="taxa de erro máxima aceitável, 0..1 (padrão: 0.01)",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="continua a rampa mesmo depois do primeiro nível que falhar",
    )
    parser.add_argument("--json", dest="json_path", help="salva o resultado em JSON")
    parser.add_argument(
        "--server-pid",
        type=int,
        help="PID do uvicorn para amostrar CPU/RSS via /proc (opcional)",
    )
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument(
        "--auction-id",
        help="usa um leilão existente; por padrão procura/cria um",
    )
    parser.add_argument(
        "--skip-room",
        action="store_true",
        help="não inclui GET /auctions/{id}/room no cenário HTTP",
    )
    args = parser.parse_args()

    try:
        levels = parse_users(args.users)
    except ValueError as exc:
        parser.error(str(exc))
    if args.http_duration <= 0:
        parser.error("--http-duration deve ser maior que zero")
    if args.ws_hold < 0:
        parser.error("--ws-hold não pode ser negativo")
    if args.ws_connect_concurrency < 1:
        parser.error("--ws-connect-concurrency deve ser pelo menos 1")
    if args.timeout <= 0:
        parser.error("--timeout deve ser maior que zero")
    if args.sla_p95_ms <= 0:
        parser.error("--sla-p95-ms deve ser maior que zero")
    if not 0 <= args.max_error_rate <= 1:
        parser.error("--max-error-rate deve estar entre 0 e 1")
    if "ws" in args.mode and websockets is None:
        print(
            "ERRO: pacote `websockets` não instalado. "
            "Rode com a venv do backend (uvicorn[standard] já o instala).",
            file=sys.stderr,
        )
        return 2

    print("AVISO: teste de carga. Use apenas em ambiente autorizado.")
    print(f"Alvo: {args.base_url}")
    print(
        f"Modo: {args.mode} | níveis: {', '.join(map(str, levels))} | "
        f"SLA p95: {format_ms(args.sla_p95_ms)} | "
        f"erros: {args.max_error_rate * 100:.1f}%"
    )
    if args.server_pid:
        print(f"Amostrando CPU/RSS do PID {args.server_pid}.")

    max_users = max(levels)
    check_fd_limit(max_users)

    http_results: list[HttpStep] = []
    ws_results: list[WsStep] = []

    async with make_client(
        args.base_url,
        concurrency=max_users + 10,
        timeout=args.timeout,
    ) as client:
        if not await ensure_api(client):
            return 2

        user = await ensure_auth(client, args.email, args.password)
        if user is None:
            print(
                "AVISO: sem autenticação; a sala HTTP será pulada.",
                file=sys.stderr,
            )

        force_create = "ws" in args.mode
        auction_id = await ensure_auction(
            client,
            user,
            args.auction_id,
            force_create=force_create,
        )
        if auction_id is None and "ws" in args.mode:
            print(
                "ERRO: não há leilão disponível para o teste WebSocket.",
                file=sys.stderr,
            )
            return 2
        if auction_id is None:
            print(
                "AVISO: nenhum leilão encontrado; o cenário HTTP terá só a listagem.",
                file=sys.stderr,
            )

        if args.mode in {"http", "both"}:
            scenario = http_scenario(
                auction_id,
                user,
                include_room=not args.skip_room,
            )
            print(
                f"\n== Rampa HTTP ({args.http_duration:.0f}s por nível) =="
            )
            print_http_header()
            for level in levels:
                check_fd_limit(level)
                step = await run_http_step(
                    client,
                    users=level,
                    duration=args.http_duration,
                    scenario=scenario,
                    sla_p95_ms=args.sla_p95_ms,
                    max_error_rate=args.max_error_rate,
                    server_pid=args.server_pid,
                )
                http_results.append(step)
                print_http_step(step)
                if not step.passed and not args.keep_going:
                    print(
                        "Parando a rampa HTTP no primeiro nível que falhou "
                        "(use --keep-going para continuar)."
                    )
                    break

        if args.mode in {"ws", "both"}:
            if user is None or auction_id is None:
                print(
                    "ERRO: teste WS exige autenticação e um leilão.",
                    file=sys.stderr,
                )
                return 2
            print(
                f"\n== Rampa WebSocket ({args.ws_hold:.0f}s de espera por nível) =="
            )
            print_ws_header()
            for level in levels:
                check_fd_limit(level)
                step = await run_ws_step(
                    base_url=args.base_url,
                    token=user.token,
                    auction_id=auction_id,
                    users=level,
                    hold=args.ws_hold,
                    connect_concurrency=args.ws_connect_concurrency,
                    timeout=args.timeout,
                    sla_p95_ms=args.sla_p95_ms,
                    max_error_rate=args.max_error_rate,
                    server_pid=args.server_pid,
                )
                ws_results.append(step)
                print_ws_step(step)
                if not step.passed and not args.keep_going:
                    print(
                        "Parando a rampa WS no primeiro nível que falhou "
                        "(use --keep-going para continuar)."
                    )
                    break

    print("\n== Resumo de capacidade ==")
    http_ok = print_capacity(
        "HTTP",
        http_results,
        args.sla_p95_ms,
        args.max_error_rate,
    )
    ws_ok = print_capacity(
        "WebSocket",
        ws_results,
        args.sla_p95_ms,
        args.max_error_rate,
    )

    if args.json_path:
        payload = {
            "base_url": args.base_url,
            "mode": args.mode,
            "sla_p95_ms": args.sla_p95_ms,
            "max_error_rate": args.max_error_rate,
            "http": [asdict(step) for step in http_results],
            "ws": [asdict(step) for step in ws_results],
        }
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        print(f"\nResultados salvos em {args.json_path}")

    return 0 if http_ok and ws_ok else 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
