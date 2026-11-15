"""Popula o banco com dados de demonstração (RNF04).

Uso:
    python seed.py

ATENÇÃO: apaga todos os dados atuais e recria as contas/leilões de demo.
A senha das contas vem de SEED_PASSWORD (backend/.env). Sem ela, o seed gera
uma senha aleatória e mostra no final: uma senha fixa no repositório público
daria acesso às contas de demonstração de qualquer ambiente publicado.

Contas:
    ana@go-horses.dev      comitente
    bruno@go-horses.dev    comprador
    carla@go-horses.dev    compradora (conta antiga, para testar pontuação)
    diego@go-horses.dev    comprador
    elisa@go-horses.dev    comitente
"""
from __future__ import annotations

import asyncio
import os
import secrets
from datetime import timedelta

from prisma.enums import AuctionStatus

from app.config import CATEGORIES, public_url
from app.db import db
from app.security import hash_password
from app.serializers import utcnow

PASSWORD = os.getenv("SEED_PASSWORD", "").strip() or secrets.token_urlsafe(12)
if len(PASSWORD) < 8:
    raise SystemExit("SEED_PASSWORD precisa ter pelo menos 8 caracteres.")


def photos(slug: str) -> list[str]:
    return [
        public_url(f"/static/demo/{slug}-{i}.svg") for i in range(1, 4)
    ]


async def main() -> None:
    await db.connect()

    # Ordem importa por causa das FKs.
    await db.bid.delete_many()
    await db.auction.delete_many()
    await db.item.delete_many()
    await db.session.delete_many()
    await db.user.delete_many()

    now = utcnow()
    password_hash = hash_password(PASSWORD)

    ana = await db.user.create(
        data={
            "email": "ana@go-horses.dev",
            "password_hash": password_hash,
            "display_name": "Ana Souza",
            "monthly_income_cents": 1_200_000,
            "created_at": now - timedelta(days=90),
        }
    )
    bruno = await db.user.create(
        data={
            "email": "bruno@go-horses.dev",
            "password_hash": password_hash,
            "display_name": "Bruno Lima",
            "monthly_income_cents": 800_000,
            "created_at": now - timedelta(days=30),
        }
    )
    carla = await db.user.create(
        data={
            "email": "carla@go-horses.dev",
            "password_hash": password_hash,
            "display_name": "Carla Mendes",
            "monthly_income_cents": 1_500_000,
            "created_at": now - timedelta(days=200),
        }
    )
    diego = await db.user.create(
        data={
            "email": "diego@go-horses.dev",
            "password_hash": password_hash,
            "display_name": "Diego Rocha",
            "monthly_income_cents": 300_000,
            "created_at": now - timedelta(days=5),
        }
    )
    elisa = await db.user.create(
        data={
            "email": "elisa@go-horses.dev",
            "password_hash": password_hash,
            "display_name": "Elisa Prado",
            "monthly_income_cents": 2_000_000,
            "created_at": now - timedelta(days=120),
        }
    )

    async def make_auction(
        *,
        seller,
        name: str,
        description: str,
        category: str,
        slug: str,
        starting_price: int,
        starts_at,
        ends_at,
        status: AuctionStatus,
        bids: list[tuple[object, int, object]] | None = None,
        winner=None,
        final_price: int | None = None,
        cancelled_at=None,
        closed_at=None,
    ):
        item = await db.item.create(
            data={
                "name": name,
                "description": description,
                "category": category,
                "photos": photos(slug),
                "seller": {"connect": {"id": seller.id}},
            }
        )
        bids = bids or []
        leader = bids[-1][0] if bids else None
        current_price = bids[-1][1] if bids else starting_price
        data: dict = {
            "item": {"connect": {"id": item.id}},
            "seller": {"connect": {"id": seller.id}},
            "status": status,
            "starting_price_cents": starting_price,
            "current_price_cents": current_price,
            "bid_count": len(bids),
            "starts_at": starts_at,
            "ends_at": ends_at,
            "original_ends_at": ends_at,
            "closed_at": closed_at,
            "cancelled_at": cancelled_at,
            "final_price_cents": final_price,
        }
        if leader is not None:
            data["leader"] = {"connect": {"id": leader.id}}
        if winner is not None:
            data["winner"] = {"connect": {"id": winner.id}}
        auction = await db.auction.create(data=data)

        for index, (bidder, amount, when) in enumerate(bids):
            await db.bid.create(
                data={
                    "auction": {"connect": {"id": auction.id}},
                    "bidder": {"connect": {"id": bidder.id}},
                    "amount_cents": amount,
                    "idempotency_key": f"seed-{auction.id}-{index}",
                    "created_at": when,
                }
            )
        return auction

    # 1) Em andamento, com lances: o caso principal da demo.
    await make_auction(
        seller=ana,
        name="Bicicleta Gravel Aro 29",
        description=(
            "Bicicleta gravel em alumínio, tamanho M, revisada. "
            "Acompanha pedais e dois suportes de garrafa."
        ),
        category="Esportes",
        slug="bike",
        starting_price=200_000,
        starts_at=now - timedelta(minutes=10),
        ends_at=now + timedelta(minutes=30),
        status=AuctionStatus.running,
        bids=[
            (bruno, 200_000, now - timedelta(minutes=6)),
            (carla, 205_000, now - timedelta(minutes=4)),
            (bruno, 210_000, now - timedelta(minutes=2)),
        ],
    )

    # 2) Agendado: abre em 2 minutos (bom para mostrar a abertura automática).
    await make_auction(
        seller=ana,
        name="Notebook ThinkPad X1 Carbon",
        description=(
            "i7, 16 GB de RAM, SSD de 512 GB, tela 14 polegadas. "
            "Bateria com boa autonomia e carregador original."
        ),
        category="Eletrônicos",
        slug="notebook",
        starting_price=350_000,
        starts_at=now + timedelta(minutes=3),
        ends_at=now + timedelta(minutes=30),
        status=AuctionStatus.scheduled,
    )

    # 3) Em andamento, sem lances: primeiro lance pode ser igual ao inicial.
    await make_auction(
        seller=elisa,
        name="Quadro Abstrato em Acrílico",
        description=(
            "Pintura original em acrílico sobre tela, 80x60 cm, "
            "assinada pela artista. Acompanha certificado."
        ),
        category="Arte e colecionáveis",
        slug="quadro",
        starting_price=30_000,
        starts_at=now - timedelta(minutes=2),
        ends_at=now + timedelta(minutes=20),
        status=AuctionStatus.running,
    )

    # 4) Vendido: encerrado com lances e vencedor.
    await make_auction(
        seller=ana,
        name="Relógio de Pulso Vintage",
        description=(
            "Relógio mecânico dos anos 1970, revisado, com pulseira de couro. "
            "Marcas de uso compatíveis com a idade."
        ),
        category="Moda",
        slug="relogio",
        starting_price=50_000,
        starts_at=now - timedelta(hours=3),
        ends_at=now - timedelta(hours=1),
        status=AuctionStatus.sold,
        bids=[
            (carla, 50_000, now - timedelta(hours=2, minutes=30)),
            (diego, 55_000, now - timedelta(hours=2)),
        ],
        winner=diego,
        final_price=55_000,
        closed_at=now - timedelta(hours=1),
    )

    # 5) Encerrado sem lances.
    await make_auction(
        seller=elisa,
        name="Violão Clássico de Nylon",
        description=(
            "Violão de estudo, tampo em cedro, cordas de nylon. "
            "Ideal para iniciantes."
        ),
        category="Outros",
        slug="violao",
        starting_price=45_000,
        starts_at=now - timedelta(hours=4),
        ends_at=now - timedelta(hours=2),
        status=AuctionStatus.unsold,
        closed_at=now - timedelta(hours=2),
    )

    # 6) Cancelado pelo comitente.
    await make_auction(
        seller=elisa,
        name="Câmera Analógica 35 mm",
        description=(
            "Câmera analógica com lente 50 mm, funcionando. "
            "Lote cancelado para demonstrar o estado final."
        ),
        category="Eletrônicos",
        slug="camera",
        starting_price=60_000,
        starts_at=now + timedelta(hours=1),
        ends_at=now + timedelta(hours=2),
        status=AuctionStatus.cancelled,
        cancelled_at=now - timedelta(minutes=5),
    )

    counts = {
        "users": await db.user.count(),
        "items": await db.item.count(),
        "auctions": await db.auction.count(),
        "bids": await db.bid.count(),
    }
    print("Banco populado com sucesso:")
    for key, value in counts.items():
        print(f"  {key}: {value}")
    print(f"\nContas de demonstração (senha: {PASSWORD}):")
    for email in (
        "ana@go-horses.dev",
        "bruno@go-horses.dev",
        "carla@go-horses.dev",
        "diego@go-horses.dev",
        "elisa@go-horses.dev",
    ):
        print(f"  {email}")
    print("\nCategorias:", ", ".join(CATEGORIES))
    await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
