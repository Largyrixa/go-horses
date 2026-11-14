"""Salas em tempo real (WebSocket), com contagem de participantes e espectadores."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from fastapi import WebSocket

from .auction_service import room_payload
from .db import db
from .errors import ApiError
from .serializers import iso, utcnow

log = logging.getLogger("gohorses.realtime")


@dataclass(eq=False)
class Client:
    websocket: WebSocket
    auction_id: str
    user_id: str
    role: str


class RoomManager:
    def __init__(self) -> None:
        self._rooms: dict[str, set[Client]] = {}
        self._lock = asyncio.Lock()

    async def add(self, client: Client) -> None:
        async with self._lock:
            self._rooms.setdefault(client.auction_id, set()).add(client)

    async def remove(self, client: Client) -> None:
        async with self._lock:
            room = self._rooms.get(client.auction_id)
            if room is not None:
                room.discard(client)
                if not room:
                    self._rooms.pop(client.auction_id, None)

    def counts(self, auction_id: str) -> dict[str, int]:
        room = self._rooms.get(auction_id, set())
        participants = sum(1 for client in room if client.role == "participant")
        spectators = sum(1 for client in room if client.role == "spectator")
        return {"participants": participants, "spectators": spectators}

    def has_participant(self, auction_id: str, user_id: str) -> bool:
        """RF10/RF25: o usuário está na sala como PARTICIPANTE (pode dar lance)?"""
        # Sem `await` no meio, nenhuma outra corrotina altera o set durante a
        # iteração (event loop single-thread), então não precisa do lock.
        return any(
            client.user_id == user_id and client.role == "participant"
            for client in self._rooms.get(auction_id, set())
        )

    async def broadcast(self, auction_id: str, payload: dict) -> None:
        room = list(self._rooms.get(auction_id, set()))
        if not room:
            return
        dead: list[Client] = []
        for client in room:
            try:
                await client.websocket.send_json(payload)
            except Exception:
                dead.append(client)
        for client in dead:
            await self.remove(client)

    async def broadcast_state(self, auction_id: str) -> None:
        counts = self.counts(auction_id)
        try:
            payload = await room_payload(db, auction_id, **counts)
        except ApiError:
            return
        except Exception:
            log.exception("Falha ao montar estado da sala %s", auction_id)
            return
        await self.broadcast(auction_id, payload)

    async def broadcast_counts(self, auction_id: str) -> None:
        counts = self.counts(auction_id)
        await self.broadcast(
            auction_id,
            {
                **counts,
                "server_time": iso(utcnow()),
            },
        )


rooms = RoomManager()
