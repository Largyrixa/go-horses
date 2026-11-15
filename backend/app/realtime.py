"""Salas em tempo real (WebSocket), com contagem de participantes e espectadores."""
from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass

from fastapi import WebSocket

from .auction_service import room_payload
from .config import CHAT_HISTORY_LIMIT
from .db import db
from .errors import ApiError
from .serializers import iso, mask_name, utcnow

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
        self._chat: dict[str, list[dict]] = {}

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
                    self._chat.pop(client.auction_id, None)

    def chat_history(self, auction_id: str) -> list[dict]:
        return list(self._chat.get(auction_id, []))

    async def chat(self, auction_id: str, user, text: str) -> None:
        """Registra e transmite uma mensagem do chat (em memória, por sala)."""
        message = {
            "id": secrets.token_hex(8),
            "user_id": user.id,
            "display_name": mask_name(user.display_name),
            "text": text,
            "sent_at": iso(utcnow()),
        }
        history = self._chat.setdefault(auction_id, [])
        history.append(message)
        if len(history) > CHAT_HISTORY_LIMIT:
            del history[: len(history) - CHAT_HISTORY_LIMIT]
        await self.broadcast(auction_id, {"type": "chat", "message": message})

    def counts(self, auction_id: str) -> dict[str, int]:
        # Conta pessoas, não conexões: a mesma conta em várias abas vale 1, e
        # quem participa em alguma aba não entra também como espectador.
        room = self._rooms.get(auction_id, set())
        participants = {c.user_id for c in room if c.role == "participant"}
        spectators = {c.user_id for c in room if c.role == "spectator"} - participants
        return {"participants": len(participants), "spectators": len(spectators)}

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
            payload = await room_payload(
                db, auction_id, **counts, chat=self.chat_history(auction_id)
            )
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
