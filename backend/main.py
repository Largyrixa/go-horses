import asyncio
import hashlib
import json
import logging
import os
import secrets
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import aiomysql
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from pydantic_settings import BaseSettings

logger = logging.getLogger("auction")
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


# =====================================================================
# CONFIGURAÇÕES (RF05, RF06, RF13, RF15)
# =====================================================================
class Settings(BaseSettings):
    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "leilao"
    db_password: str = "leilao_secret"
    db_name: str = "leilao"

    public_base_url: str = "http://200.18.99.113:8088"
    upload_dir: str = "/tmp/leilao_uploads"

    session_ttl_minutes: int = 120
    session_sliding_renewal: bool = True

    title_min_len: int = 2
    title_max_len: int = 120
    description_min_len: int = 5
    description_max_len: int = 4000
    min_photos: int = 3
    max_photos: int = 10
    max_photo_mb: int = 5
    allowed_categories: list[str] = [
        "Arte",
        "Colecionáveis",
        "Eletrônicos",
        "Imóveis",
        "Joias e Relógios",
        "Móveis",
        "Veículos",
        "Outros",
    ]

    # Limites fáceis de alterar para a demo (RF06)
    min_lead_seconds: int = 10
    max_lead_days: int = 30
    min_duration_seconds: int = 30
    max_duration_days: int = 14

    # Prorrogação (RF15) e rate-limit (RF13)
    anti_snipe_window_seconds: int = 120
    anti_snipe_extend_seconds: int = 120
    anti_snipe_max_total_seconds: int = 1800
    min_bid_interval_ms: int = 500
    worker_poll_interval_seconds: float = 0.5

    # Desligado por padrão porque Cadastro.jsx envia apenas nome, e-mail e senha
    enable_bonus_credit_rules: bool = False


settings = Settings()
os.makedirs(settings.upload_dir, exist_ok=True)
pool: aiomysql.Pool | None = None

# Mapeamento entre status do SQL do usuário e status do Frontend React
DB_TO_FRONT_STATUS = {
    "AGENDADO": "scheduled",
    "EM_ANDAMENTO": "running",
    "VENDIDO": "sold",
    "ENCERRADO_SEM_LANCES": "unsold",
    "CANCELADO": "cancelled",
}
FRONT_TO_DB_STATUS = {v: k for k, v in DB_TO_FRONT_STATUS.items()}


def get_pool() -> aiomysql.Pool:
    assert pool is not None, "Pool MySQL não inicializado"
    return pool


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def parse_json_col(val):
    return json.loads(val) if isinstance(val, str) else val


async def fetchone(cur, sql: str, params: tuple = ()) -> dict | None:
    await cur.execute(sql, params)
    return await cur.fetchone()


async def fetchall(cur, sql: str, params: tuple = ()) -> list[dict]:
    await cur.execute(sql, params)
    return await cur.fetchall()


# =====================================================================
# REGRAS DE NEGÓCIO (RF14, RF15, RF23, RF29-RF32)
# =====================================================================
def calculate_next_min_bid(current_price_cents: int) -> int:
    if current_price_cents < 10_000:
        inc = 100
    elif current_price_cents < 50_000:
        inc = 500
    elif current_price_cents < 100_000:
        inc = 1_000
    elif current_price_cents < 500_000:
        inc = 5_000
    elif current_price_cents < 2_500_000:
        inc = 10_000
    else:
        inc = 50_000
    return current_price_cents + inc


def calculate_extended_ends_at(
    now: datetime, ends_at: datetime, original_ends_at: datetime
) -> datetime:
    if (ends_at - now).total_seconds() >= settings.anti_snipe_window_seconds:
        return ends_at
    candidate = now + timedelta(seconds=settings.anti_snipe_extend_seconds)
    hard_cap = original_ends_at + timedelta(seconds=settings.anti_snipe_max_total_seconds)
    return min(max(ends_at, candidate), hard_cap)


def can_cancel_auction(db_status: str, bid_count: int) -> bool:
    return db_status == "AGENDADO" or (db_status == "EM_ANDAMENTO" and bid_count == 0)


async def get_user_score_and_credit(cur, user_id: str) -> dict:
    row = await fetchone(
        cur,
        """
        SELECT
            u.monthly_income_cents,
            u.seller_enabled_at,
            TIMESTAMPDIFF(SECOND, u.created_at, UTC_TIMESTAMP(6)) / 86400.0 AS account_days,
            (SELECT COUNT(*) FROM auctions WHERE leader_id = u.id AND status = 'VENDIDO') AS wins,
            (SELECT COALESCE(SUM(current_price), 0) FROM auctions WHERE leader_id = u.id AND status = 'VENDIDO') AS total_bought_cents,
            (SELECT COALESCE(SUM(current_price), 0) FROM auctions WHERE leader_id = u.id AND status = 'EM_ANDAMENTO') AS reserved_cents
        FROM users u
        WHERE u.id = %s
        """,
        (user_id,),
    )
    income_reais = (row["monthly_income_cents"] or 0) / 100.0
    days = max(0.0, float(row["account_days"] or 0.0))
    wins = int(row["wins"])
    bought_reais = float(row["total_bought_cents"]) / 100.0

    score = round(
        50.0 * min(income_reais / 10_000.0, 1.0)
        + 20.0 * min(days / 180.0, 1.0)
        + 15.0 * min(wins / 10.0, 1.0)
        + 15.0 * min(bought_reais / 20_000.0, 1.0),
        2,
    )
    income_cents = int(row["monthly_income_cents"] or 0)
    credit_limit_cents = int((income_cents * 6 * score) // 100)
    reserved_cents = int(row["reserved_cents"])

    return {
        "score": score,
        "seller_enabled": row["seller_enabled_at"] is not None,
        "credit_limit_cents": credit_limit_cents,
        "reserved_cents": reserved_cents,
        "available_credit_cents": max(0, credit_limit_cents - reserved_cents),
    }


# =====================================================================
# SERIALIZADORES NO FORMATO EXATO DO FRONTEND REACT
# =====================================================================
def format_auction_for_front(row: dict) -> dict:
    photos = parse_json_col(row.get("photos")) or []
    db_status = row["status"]
    front_status = DB_TO_FRONT_STATUS.get(db_status, db_status.lower())
    bid_count = int(row.get("bid_count") or 0)
    current_price = int(row["current_price"])
    start_price = int(row["start_price"])

    leader_obj = None
    if bid_count > 0 and row.get("leader_id"):
        leader_obj = {
            "id": row["leader_id"],
            "display_name": row.get("leader_name") or "Líder",
        }

    winner_obj = leader_obj if front_status == "sold" else None

    return {
        "id": row["id"],
        "item_id": row["item_id"],
        "name": row["title"],
        "title": row["title"],
        "description": row.get("description", ""),
        "category": row["category"],
        "photos": photos,
        "cover_photo": photos[0] if photos else None,
        "status": front_status,
        "starting_price": start_price,
        "start_price": start_price,
        "current_price": current_price,
        "min_bid": int(row["current_min_bid"]),
        "current_min_bid": int(row["current_min_bid"]),
        "final_price": current_price if front_status == "sold" else None,
        "bid_count": bid_count,
        "starts_at": to_utc_iso(row["starts_at"]),
        "ends_at": to_utc_iso(row["ends_at"]),
        "server_now": to_utc_iso(utcnow_naive()),
        "seller": {
            "id": row["owner_id"],
            "display_name": row.get("seller_name") or "Comitente",
        },
        "leader": leader_obj,
        "winner": winner_obj,
    }


def format_bid_for_front(row: dict) -> dict:
    name = row.get("display_name") or row.get("bidder_name") or "Participante"
    return {
        "id": row["id"],
        "amount": int(row["amount"]),
        "seq": int(row["seq"]),
        "created_at": to_utc_iso(row["created_at"]),
        "bidder_name": name,
        "bidder": {
            "id": row["user_id"],
            "display_name": name,
        },
    }


async def load_full_auction(cur, auction_id: str) -> dict | None:
    row = await fetchone(
        cur,
        """
        SELECT a.*, i.owner_id, i.title, i.description, i.category, i.photos,
               seller.display_name AS seller_name,
               leader.display_name AS leader_name
        FROM auctions a
        JOIN items i ON i.id = a.item_id
        JOIN users seller ON seller.id = i.owner_id
        LEFT JOIN users leader ON leader.id = a.leader_id
        WHERE a.id = %s
        """,
        (auction_id,),
    )
    return format_auction_for_front(row) if row else None


async def load_room_counts(cur, auction_id: str) -> dict:
    row = await fetchone(
        cur,
        """
        SELECT
            COALESCE(SUM(role = 'PARTICIPANTE'), 0) AS participants,
            COALESCE(SUM(role = 'ESPECTADOR'), 0) AS spectators
        FROM auction_presence
        WHERE auction_id = %s
        """,
        (auction_id,),
    )
    return {
        "participants": int(row["participants"]),
        "spectators": int(row["spectators"]),
    }


# =====================================================================
# TEMPO REAL MULTI-INSTÂNCIA (WebSocket + tabela auction_events)
# =====================================================================
class RealtimeHub:
    def __init__(self) -> None:
        self.rooms: dict[str, set[WebSocket]] = defaultdict(set)
        self.user_sockets: dict[tuple[str, str], set[WebSocket]] = defaultdict(set)
        self._last_event_id: int = 0

    async def init_cursor(self) -> None:
        async with get_pool().acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                row = await fetchone(cur, "SELECT COALESCE(MAX(id), 0) AS max_id FROM auction_events")
                self._last_event_id = int(row["max_id"])

    async def publish(self, cur, event: dict) -> None:
        await cur.execute(
            """
            INSERT INTO auction_events (auction_id, target_user_id, payload)
            VALUES (%s, %s, %s)
            """,
            (
                str(event["auction_id"]),
                str(event["target_user_id"]) if event.get("target_user_id") else None,
                json.dumps(event, default=str),
            ),
        )

    async def _dispatch_local(self, event: dict) -> None:
        auction_id = str(event["auction_id"])
        target_user_id = event.get("target_user_id")
        raw = json.dumps(event, default=str)
        targets = (
            list(self.user_sockets.get((auction_id, str(target_user_id)), []))
            if target_user_id
            else list(self.rooms.get(auction_id, []))
        )
        for ws in targets:
            try:
                await ws.send_text(raw)
            except Exception:
                pass

    async def poll_loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                async with get_pool().acquire() as conn:
                    async with conn.cursor(aiomysql.DictCursor) as cur:
                        rows = await fetchall(
                            cur,
                            "SELECT id, payload FROM auction_events WHERE id > %s ORDER BY id ASC LIMIT 200",
                            (self._last_event_id,),
                        )
                        for r in rows:
                            self._last_event_id = int(r["id"])
                            await self._dispatch_local(parse_json_col(r["payload"]))
            except Exception as exc:
                logger.exception("Erro no dispatcher de eventos WS: %s", exc)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=0.1)
            except asyncio.TimeoutError:
                pass

    def register(self, auction_id: str, user_id: str, ws: WebSocket) -> None:
        self.rooms[auction_id].add(ws)
        self.user_sockets[(auction_id, user_id)].add(ws)

    def unregister(self, auction_id: str, user_id: str, ws: WebSocket) -> int:
        self.rooms[auction_id].discard(ws)
        sockets = self.user_sockets[(auction_id, user_id)]
        sockets.discard(ws)
        return len(sockets)


hub = RealtimeHub()


# =====================================================================
# WORKER AUTOMÁTICO DE ABERTURA E FECHAMENTO (RF17 / RF18)
# =====================================================================
async def process_due_transitions() -> None:
    async with get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            # 1) Abrir leilões AGENDADO
            await conn.begin()
            try:
                to_open = await fetchall(
                    cur,
                    """
                    SELECT id FROM auctions
                    WHERE status = 'AGENDADO' AND starts_at <= UTC_TIMESTAMP(6)
                    FOR UPDATE SKIP LOCKED
                    """,
                )
                for row in to_open:
                    await cur.execute(
                        "UPDATE auctions SET status = 'EM_ANDAMENTO' WHERE id = %s",
                        (row["id"],),
                    )
                    full = await load_full_auction(cur, row["id"])
                    await hub.publish(cur, {
                        "type": "auction_opened",
                        "auction_id": row["id"],
                        "auction": full,
                    })
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

            # 2) Fechar leilões EM_ANDAMENTO
            await conn.begin()
            try:
                to_close = await fetchall(
                    cur,
                    """
                    SELECT id, bid_count FROM auctions
                    WHERE status = 'EM_ANDAMENTO' AND ends_at <= UTC_TIMESTAMP(6)
                    FOR UPDATE SKIP LOCKED
                    """,
                )
                for row in to_close:
                    new_status = "VENDIDO" if row["bid_count"] > 0 else "ENCERRADO_SEM_LANCES"
                    await cur.execute(
                        "UPDATE auctions SET status = %s, closed_at = UTC_TIMESTAMP(6) WHERE id = %s",
                        (new_status, row["id"]),
                    )
                    full = await load_full_auction(cur, row["id"])
                    await hub.publish(cur, {
                        "type": "auction_closed",
                        "auction_id": row["id"],
                        "auction": full,
                    })
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise


async def worker_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await process_due_transitions()
        except Exception as exc:
            logger.exception("Erro no worker de leilões: %s", exc)
        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=settings.worker_poll_interval_seconds
            )
        except asyncio.TimeoutError:
            pass


# =====================================================================
# LIFECYCLE, APP FASTAPI & CORS
# =====================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await aiomysql.create_pool(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        db=settings.db_name,
        minsize=5,
        maxsize=30,
        autocommit=True,
        charset="utf8mb4",
    )
    await hub.init_cursor()
    stop_event = asyncio.Event()
    t_worker = asyncio.create_task(worker_loop(stop_event))
    t_events = asyncio.create_task(hub.poll_loop(stop_event))
    yield
    stop_event.set()
    await t_worker
    await t_events
    pool.close()
    await pool.wait_closed()


app = FastAPI(title="GoHorse Leilão Online API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")


# Preserva campos extras como min_bid nas respostas de erro HTTP (exigido pelo Sala.jsx: e.minBid)
@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "message": exc.detail})


# =====================================================================
# SCHEMAS & AUTENTICAÇÃO
# =====================================================================
class RegisterIn(BaseModel):
    display_name: str
    email: EmailStr
    password: str = Field(min_length=8)
    monthly_income_cents: int | None = Field(default=None, ge=0)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class CreateAuctionIn(BaseModel):
    name: str | None = None
    title: str | None = None
    description: str
    category: str
    photos: list[str]
    starting_price: int | None = Field(default=None, gt=0)
    start_price: int | None = Field(default=None, gt=0)
    starts_at: datetime
    duration_seconds: int


class PlaceBidIn(BaseModel):
    amount: int = Field(gt=0)
    idempotency_key: UUID


class RoleSwitchIn(BaseModel):
    role: str


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


async def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sessão ausente ou inválida")
    raw_token = authorization.removeprefix("Bearer ").strip()
    token_h = hash_token(raw_token)
    async with get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            row = await fetchone(
                cur,
                """
                SELECT s.id AS session_id, u.id, u.display_name, u.email,
                       u.monthly_income_cents, u.seller_enabled_at, u.created_at
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = %s AND s.revoked_at IS NULL AND s.expires_at > UTC_TIMESTAMP(6)
                """,
                (token_h,),
            )
            if not row:
                raise HTTPException(status_code=401, detail="Sessão expirada ou inválida")
            if settings.session_sliding_renewal:
                await cur.execute(
                    "UPDATE sessions SET expires_at = DATE_ADD(UTC_TIMESTAMP(6), INTERVAL %s MINUTE) WHERE id = %s",
                    (settings.session_ttl_minutes, row["session_id"]),
                )
            return row


def _validate_item_and_times(
    title: str,
    description: str,
    category: str,
    photos: list[str],
    starts_at: datetime,
    duration_seconds: int,
) -> tuple[datetime, datetime]:
    if not (settings.title_min_len <= len(title.strip()) <= settings.title_max_len):
        raise HTTPException(status_code=422, detail="Tamanho do nome do item inválido")
    if not (settings.description_min_len <= len(description.strip()) <= settings.description_max_len):
        raise HTTPException(status_code=422, detail="Tamanho da descrição inválido")
    if not category or not category.strip():
        raise HTTPException(status_code=422, detail="Categoria obrigatória")
    if not (settings.min_photos <= len(photos) <= settings.max_photos):
        raise HTTPException(
            status_code=422, detail=f"Envie entre {settings.min_photos} e {settings.max_photos} fotos"
        )

    now = utcnow_naive()
    if starts_at.tzinfo is not None:
        starts_at = starts_at.astimezone(timezone.utc).replace(tzinfo=None)
    lead = (starts_at - now).total_seconds()
    if not (settings.min_lead_seconds <= lead <= settings.max_lead_days * 86400):
        raise HTTPException(status_code=422, detail="Horário de início fora dos limites permitidos")
    if not (settings.min_duration_seconds <= duration_seconds <= settings.max_duration_days * 86400):
        raise HTTPException(status_code=422, detail="Duração fora dos limites permitidos")
    return starts_at, starts_at + timedelta(seconds=duration_seconds)


# =====================================================================
# ROTAS: CONTAS & SESSÕES (Cadastro.jsx, Login.jsx, auth.jsx)
# =====================================================================
@app.post("/auth/register", status_code=201)
async def register(body: RegisterIn):
    user_id = str(uuid4())
    async with get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await cur.execute(
                    """
                    INSERT INTO users (id, display_name, email, password_hash, monthly_income_cents)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        body.display_name.strip(),
                        body.email,
                        pwd_ctx.hash(body.password),
                        body.monthly_income_cents,
                    ),
                )
            except aiomysql.IntegrityError:
                raise HTTPException(status_code=409, detail="E-mail já cadastrado")
            user = await fetchone(
                cur,
                "SELECT id, display_name, email, created_at FROM users WHERE id = %s",
                (user_id,),
            )
    user["created_at"] = to_utc_iso(user["created_at"])
    return user


@app.post("/auth/login")
async def login(body: LoginIn):
    async with get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            user = await fetchone(cur, "SELECT * FROM users WHERE email = %s", (body.email,))
            if not user or not pwd_ctx.verify(body.password, user["password_hash"]):
                raise HTTPException(status_code=401, detail="Credenciais inválidas")
            raw_token = secrets.token_urlsafe(32)
            expires_at = utcnow_naive() + timedelta(minutes=settings.session_ttl_minutes)
            await cur.execute(
                "INSERT INTO sessions (id, user_id, token_hash, expires_at) VALUES (%s, %s, %s, %s)",
                (str(uuid4()), user["id"], hash_token(raw_token), expires_at),
            )
    user_out = {
        "id": user["id"],
        "display_name": user["display_name"],
        "email": user["email"],
    }
    return {
        "token": raw_token,
        "access_token": raw_token,
        "expires_at": to_utc_iso(expires_at),
        "user": user_out,
    }


@app.post("/auth/logout")
async def logout(authorization: str | None = Header(default=None)):
    if authorization and authorization.startswith("Bearer "):
        token_h = hash_token(authorization.removeprefix("Bearer ").strip())
        async with get_pool().acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE sessions SET revoked_at = UTC_TIMESTAMP(6) WHERE token_hash = %s",
                    (token_h,),
                )
    return {"ok": True}


@app.get("/auth/me")
@app.get("/users/me")
async def auth_me(user=Depends(get_current_user)):
    return {
        "id": user["id"],
        "display_name": user["display_name"],
        "email": user["email"],
    }


# =====================================================================
# ROTAS: CATEGORIAS & UPLOAD DE FOTOS (NovoLeilao.jsx, Home.jsx)
# =====================================================================
@app.get("/categories")
async def get_categories():
    return settings.allowed_categories


@app.post("/uploads")
@app.post("/upload")
@app.post("/photos")
async def upload_photo_endpoint(file: UploadFile = File(...), user=Depends(get_current_user)):
    allowed_types = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=422, detail="Formato inválido. Use JPG, PNG ou WebP.")
    content = await file.read()
    if len(content) > settings.max_photo_mb * 1024 * 1024:
        raise HTTPException(status_code=422, detail=f"Arquivo excede {settings.max_photo_mb} MB.")

    filename = f"{uuid4().hex}{allowed_types[file.content_type]}"
    dest = Path(settings.upload_dir) / filename
    dest.write_bytes(content)

    url = f"{settings.public_base_url.rstrip('/')}/uploads/{filename}"
    return {"url": url}


# =====================================================================
# ROTAS: LEILÕES (Home.jsx, NovoLeilao.jsx, Detalhe.jsx, MeusLeiloes.jsx)
# =====================================================================
@app.post("/auctions", status_code=201)
async def create_auction(body: CreateAuctionIn, user=Depends(get_current_user)):
    item_name = (body.name or body.title or "").strip()
    start_price = body.starting_price or body.start_price
    if not start_price or start_price <= 0:
        raise HTTPException(status_code=422, detail="Preço inicial deve ser maior que zero")

    starts_at, ends_at = _validate_item_and_times(
        item_name, body.description, body.category, body.photos, body.starts_at, body.duration_seconds
    )
    item_id = str(uuid4())
    auction_id = str(uuid4())

    async with get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await conn.begin()
            try:
                await cur.execute(
                    """
                    INSERT INTO items (id, owner_id, title, description, category, photos)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        item_id,
                        user["id"],
                        item_name,
                        body.description.strip(),
                        body.category.strip(),
                        json.dumps(body.photos),
                    ),
                )
                await cur.execute(
                    """
                    INSERT INTO auctions (
                        id, item_id, status, start_price, current_price, current_min_bid,
                        starts_at, ends_at, original_ends_at
                    )
                    VALUES (%s, %s, 'AGENDADO', %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        auction_id,
                        item_id,
                        start_price,
                        start_price,
                        start_price,
                        starts_at,
                        ends_at,
                        ends_at,
                    ),
                )
                created = await load_full_auction(cur, auction_id)
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
    return created


@app.get("/auctions")
async def list_auctions(
    q: str | None = Query(default=None),
    category: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=100),
):
    clauses = ["1=1"]
    params: list = []

    if status:
        db_st = FRONT_TO_DB_STATUS.get(status, status.upper())
        clauses.append("a.status = %s")
        params.append(db_st)
    else:
        clauses.append("a.status IN ('AGENDADO', 'EM_ANDAMENTO')")

    if category:
        clauses.append("i.category = %s")
        params.append(category)

    if q and q.strip():
        clauses.append("i.title LIKE CONCAT('%%', %s, '%%')")
        params.append(q.strip())

    offset = (page - 1) * page_size
    sql = f"""
        SELECT a.*, i.owner_id, i.title, i.description, i.category, i.photos,
               seller.display_name AS seller_name,
               leader.display_name AS leader_name
        FROM auctions a
        JOIN items i ON i.id = a.item_id
        JOIN users seller ON seller.id = i.owner_id
        LEFT JOIN users leader ON leader.id = a.leader_id
        WHERE {' AND '.join(clauses)}
        ORDER BY (a.status = 'EM_ANDAMENTO') DESC, a.ends_at ASC
        LIMIT %s OFFSET %s
    """
    params.extend([page_size + 1, offset])

    async with get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            rows = await fetchall(cur, sql, tuple(params))

    has_more = len(rows) > page_size
    items = [format_auction_for_front(r) for r in rows[:page_size]]
    return {"items": items, "has_more": has_more, "page": page}


@app.get("/auctions/mine")
@app.get("/me/auctions")
@app.get("/users/me/auctions")
async def my_auctions(user=Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            rows = await fetchall(
                cur,
                """
                SELECT a.*, i.owner_id, i.title, i.description, i.category, i.photos,
                       seller.display_name AS seller_name,
                       leader.display_name AS leader_name
                FROM auctions a
                JOIN items i ON i.id = a.item_id
                JOIN users seller ON seller.id = i.owner_id
                LEFT JOIN users leader ON leader.id = a.leader_id
                WHERE i.owner_id = %s
                ORDER BY a.created_at DESC
                """,
                (user["id"],),
            )
    items = [format_auction_for_front(r) for r in rows]
    return {"items": items}


@app.get("/auctions/{auction_id}")
async def get_auction_detail(auction_id: UUID):
    aid = str(auction_id)
    async with get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            auction = await load_full_auction(cur, aid)
            if not auction:
                raise HTTPException(status_code=404, detail="Leilão não encontrado")

            recent_bids = await fetchall(
                cur,
                """
                SELECT b.id, b.amount, b.seq, b.created_at, b.user_id, u.display_name
                FROM bids b
                JOIN users u ON u.id = b.user_id
                WHERE b.auction_id = %s
                ORDER BY b.seq DESC
                LIMIT 20
                """,
                (aid,),
            )
            counts = await load_room_counts(cur, aid)

    auction["bids"] = [format_bid_for_front(b) for b in recent_bids]
    auction["counts"] = counts
    return auction


@app.post("/auctions/{auction_id}/cancel")
async def cancel_auction(auction_id: UUID, user=Depends(get_current_user)):
    aid = str(auction_id)
    async with get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await conn.begin()
            try:
                row = await fetchone(
                    cur,
                    """
                    SELECT a.id, a.status, a.bid_count, i.owner_id
                    FROM auctions a JOIN items i ON i.id = a.item_id
                    WHERE a.id = %s FOR UPDATE
                    """,
                    (aid,),
                )
                if not row:
                    raise HTTPException(status_code=404, detail="Leilão não encontrado")
                if row["owner_id"] != user["id"]:
                    raise HTTPException(status_code=403, detail="Apenas o comitente pode cancelar")
                if not can_cancel_auction(row["status"], row["bid_count"]):
                    raise HTTPException(status_code=409, detail="Leilões com lances não podem ser cancelados")

                await cur.execute(
                    "UPDATE auctions SET status = 'CANCELADO', cancelled_at = UTC_TIMESTAMP(6) WHERE id = %s",
                    (aid,),
                )
                updated = await load_full_auction(cur, aid)
                await hub.publish(cur, {
                    "type": "auction_cancelled",
                    "auction_id": aid,
                    "auction": updated,
                })
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
    return updated


# =====================================================================
# ROTAS: LANCES & MINHAS PARTICIPAÇÕES (Sala.jsx, Participacoes.jsx)
# =====================================================================
@app.post("/auctions/{auction_id}/bids")
async def place_bid(auction_id: UUID, body: PlaceBidIn, user=Depends(get_current_user)):
    aid = str(auction_id)
    idem = str(body.idempotency_key)

    async with get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            # 1) Idempotência (RF12)
            existing = await fetchone(
                cur,
                """
                SELECT b.id, b.amount, b.seq, b.created_at, b.user_id, u.display_name
                FROM bids b JOIN users u ON u.id = b.user_id
                WHERE b.auction_id = %s AND b.user_id = %s AND b.idempotency_key = %s
                """,
                (aid, user["id"], idem),
            )
            if existing:
                full_auction = await load_full_auction(cur, aid)
                return {
                    "idempotent_replay": True,
                    "auction": full_auction,
                    "bid": format_bid_for_front(existing),
                }

            await conn.begin()
            try:
                auction = await fetchone(
                    cur,
                    """
                    SELECT a.*, i.owner_id
                    FROM auctions a JOIN items i ON i.id = a.item_id
                    WHERE a.id = %s
                    FOR UPDATE OF a
                    """,
                    (aid,),
                )
                if not auction:
                    raise HTTPException(status_code=404, detail="Leilão não encontrado")

                existing_locked = await fetchone(
                    cur,
                    """
                    SELECT b.id, b.amount, b.seq, b.created_at, b.user_id, u.display_name
                    FROM bids b JOIN users u ON u.id = b.user_id
                    WHERE b.auction_id = %s AND b.user_id = %s AND b.idempotency_key = %s
                    """,
                    (aid, user["id"], idem),
                )
                if existing_locked:
                    full_auction = await load_full_auction(cur, aid)
                    await conn.commit()
                    return {
                        "idempotent_replay": True,
                        "auction": full_auction,
                        "bid": format_bid_for_front(existing_locked),
                    }

                now = utcnow_naive()
                min_bid = int(auction["current_min_bid"])

                def reject(status_code: int, message: str):
                    raise HTTPException(
                        status_code=status_code,
                        detail={"message": message, "detail": message, "min_bid": min_bid, "minBid": min_bid},
                    )

                if auction["status"] != "EM_ANDAMENTO" or now >= auction["ends_at"]:
                    reject(409, "O leilão não está em andamento ou já encerrou.")
                if auction["owner_id"] == user["id"]:
                    reject(403, "O comitente não pode dar lance no próprio leilão.")
                if auction["leader_id"] == user["id"]:
                    reject(409, "Você já é o líder atual deste leilão.")

                presence = await fetchone(
                    cur,
                    "SELECT role FROM auction_presence WHERE auction_id = %s AND user_id = %s",
                    (aid, user["id"]),
                )
                if not presence or presence["role"] != "PARTICIPANTE":
                    reject(403, "Entre na sala como participante para dar lances.")

                last_bid_row = await fetchone(
                    cur,
                    "SELECT created_at FROM bids WHERE user_id = %s ORDER BY created_at DESC LIMIT 1",
                    (user["id"],),
                )
                if (
                    last_bid_row
                    and (now - last_bid_row["created_at"]).total_seconds() * 1000
                    < settings.min_bid_interval_ms
                ):
                    reject(429, "Aguarde alguns instantes antes de enviar outro lance.")

                if body.amount < min_bid:
                    reject(422, "O valor informado é menor que o lance mínimo vigente.")

                if settings.enable_bonus_credit_rules:
                    credit = await get_user_score_and_credit(cur, user["id"])
                    if body.amount > credit["available_credit_cents"]:
                        reject(403, "Crédito disponível insuficiente para cobrir este lance.")

                previous_leader_id = auction["leader_id"]
                new_seq = int(auction["bid_count"]) + 1
                next_min_bid = calculate_next_min_bid(body.amount)
                new_ends_at = calculate_extended_ends_at(
                    now, auction["ends_at"], auction["original_ends_at"]
                )
                bid_id = str(uuid4())

                await cur.execute(
                    """
                    INSERT INTO bids (id, auction_id, user_id, amount, seq, idempotency_key, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (bid_id, aid, user["id"], body.amount, new_seq, idem, now),
                )

                await cur.execute(
                    """
                    UPDATE auctions
                    SET current_price = %s,
                        current_min_bid = %s,
                        leader_id = %s,
                        bid_count = %s,
                        ends_at = %s
                    WHERE id = %s
                    """,
                    (body.amount, next_min_bid, user["id"], new_seq, new_ends_at, aid),
                )

                full_auction = await load_full_auction(cur, aid)
                bid_out = format_bid_for_front({
                    "id": bid_id,
                    "amount": body.amount,
                    "seq": new_seq,
                    "created_at": now,
                    "user_id": user["id"],
                    "display_name": user["display_name"],
                })

                await hub.publish(cur, {
                    "type": "bid",
                    "auction_id": aid,
                    "auction": full_auction,
                    "bid": bid_out,
                })

                if previous_leader_id and previous_leader_id != user["id"]:
                    await hub.publish(cur, {
                        "type": "outbid",
                        "auction_id": aid,
                        "target_user_id": previous_leader_id,
                        "auction": full_auction,
                    })

                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    return {
        "idempotent_replay": False,
        "auction": full_auction,
        "bid": bid_out,
    }


@app.get("/participations")
@app.get("/me/participations")
@app.get("/users/me/participations")
async def my_participations(user=Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            rows = await fetchall(
                cur,
                """
                SELECT a.*, i.owner_id, i.title, i.description, i.category, i.photos,
                       seller.display_name AS seller_name,
                       leader.display_name AS leader_name,
                       my.my_top_bid
                FROM (
                    SELECT auction_id, MAX(amount) AS my_top_bid
                    FROM bids
                    WHERE user_id = %s
                    GROUP BY auction_id
                ) my
                JOIN auctions a ON a.id = my.auction_id
                JOIN items i ON i.id = a.item_id
                JOIN users seller ON seller.id = i.owner_id
                LEFT JOIN users leader ON leader.id = a.leader_id
                ORDER BY a.ends_at DESC
                """,
                (user["id"],),
            )
    items = []
    for r in rows:
        auction_obj = format_auction_for_front(r)
        if r["status"] == "VENDIDO" and r["leader_id"] == user["id"]:
            situation = "won"
        elif r["status"] == "EM_ANDAMENTO" and r["leader_id"] == user["id"]:
            situation = "leader"
        else:
            situation = "outbid"

        items.append({
            "auction": auction_obj,
            "situation": situation,
            "my_top_bid": int(r["my_top_bid"]),
        })
    return {"items": items}


# =====================================================================
# SALA EM TEMPO REAL (WebSocket + Presença Participante/Espectador)
# =====================================================================
def _normalize_role(role: str) -> str:
    r = role.strip().lower()
    return "ESPECTADOR" if r in ("spectator", "espectador") else "PARTICIPANTE"


async def _broadcast_presence(cur, auction_id: str) -> dict:
    counts = await load_room_counts(cur, auction_id)
    await hub.publish(cur, {
        "type": "presence",
        "auction_id": auction_id,
        "counts": counts,
    })
    return counts


@app.post("/auctions/{auction_id}/presence")
@app.post("/auctions/{auction_id}/presence/role")
async def switch_presence_role(
    auction_id: UUID, body: RoleSwitchIn, user=Depends(get_current_user)
):
    aid = str(auction_id)
    db_role = _normalize_role(body.role)
    async with get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            auction = await fetchone(
                cur,
                "SELECT a.current_min_bid, i.owner_id FROM auctions a JOIN items i ON i.id = a.item_id WHERE a.id = %s",
                (aid,),
            )
            if not auction:
                raise HTTPException(status_code=404, detail="Leilão não encontrado")
            if auction["owner_id"] == user["id"]:
                db_role = "ESPECTADOR"

            await cur.execute(
                """
                INSERT INTO auction_presence (auction_id, user_id, role, last_seen_at)
                VALUES (%s, %s, %s, UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE role = VALUES(role), last_seen_at = UTC_TIMESTAMP(6)
                """,
                (aid, user["id"], db_role),
            )
            counts = await _broadcast_presence(cur, aid)
    return {"role": "spectator" if db_role == "ESPECTADOR" else "participant", "counts": counts}


@app.websocket("/ws/auctions/{auction_id}")
async def auction_room_ws(
    websocket: WebSocket,
    auction_id: UUID,
    token: str | None = Query(default=None),
    role: str = Query(default="participant"),
):
    aid = str(auction_id)
    raw_token = token
    if not raw_token:
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            raw_token = auth_header.removeprefix("Bearer ").strip()

    if not raw_token:
        await websocket.close(code=4401)
        return

    async with get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            user = await fetchone(
                cur,
                """
                SELECT u.id, u.display_name FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = %s AND s.revoked_at IS NULL AND s.expires_at > UTC_TIMESTAMP(6)
                """,
                (hash_token(raw_token),),
            )
            if not user:
                await websocket.close(code=4401)
                return

            auction_row = await fetchone(
                cur,
                "SELECT a.current_min_bid, i.owner_id FROM auctions a JOIN items i ON i.id = a.item_id WHERE a.id = %s",
                (aid,),
            )
            if not auction_row:
                await websocket.close(code=4404)
                return

            db_role = _normalize_role(role)
            if auction_row["owner_id"] == user["id"]:
                db_role = "ESPECTADOR"

            await websocket.accept()
            hub.register(aid, user["id"], websocket)

            await cur.execute(
                """
                INSERT INTO auction_presence (auction_id, user_id, role, last_seen_at)
                VALUES (%s, %s, %s, UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE role = VALUES(role), last_seen_at = UTC_TIMESTAMP(6)
                """,
                (aid, user["id"], db_role),
            )
            counts = await _broadcast_presence(cur, aid)

            # Envia o snapshot inicial completo assim que o cliente conecta
            full_auction = await load_full_auction(cur, aid)
            recent_bids = await fetchall(
                cur,
                """
                SELECT b.id, b.amount, b.seq, b.created_at, b.user_id, u.display_name
                FROM bids b JOIN users u ON u.id = b.user_id
                WHERE b.auction_id = %s
                ORDER BY b.seq DESC
                LIMIT 20
                """,
                (aid,),
            )
            await websocket.send_text(json.dumps({
                "type": "snapshot",
                "auction_id": aid,
                "auction": full_auction,
                "bids": [format_bid_for_front(b) for b in recent_bids],
                "counts": counts,
            }, default=str))

    try:
        while True:
            msg_text = await websocket.receive_text()
            async with get_pool().acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    try:
                        msg = json.loads(msg_text)
                        if isinstance(msg, dict) and msg.get("role"):
                            new_role = _normalize_role(str(msg["role"]))
                            if auction_row["owner_id"] == user["id"]:
                                new_role = "ESPECTADOR"
                            await cur.execute(
                                "UPDATE auction_presence SET role=%s, last_seen_at=UTC_TIMESTAMP(6) WHERE auction_id=%s AND user_id=%s",
                                (new_role, aid, user["id"]),
                            )
                            await _broadcast_presence(cur, aid)
                            continue
                    except Exception:
                        pass

                    await cur.execute(
                        "UPDATE auction_presence SET last_seen_at = UTC_TIMESTAMP(6) WHERE auction_id=%s AND user_id=%s",
                        (aid, user["id"]),
                    )
    except WebSocketDisconnect:
        remaining_tabs = hub.unregister(aid, user["id"], websocket)
        if remaining_tabs == 0:
            async with get_pool().acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(
                        "DELETE FROM auction_presence WHERE auction_id=%s AND user_id=%s",
                        (aid, user["id"]),
                    )
                    await _broadcast_presence(cur, aid)