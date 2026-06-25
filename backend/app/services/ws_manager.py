"""WebSocket connection manager — singleton for managing live client connections."""
import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Optional
from fastapi import WebSocket


@dataclass
class Connection:
    websocket: WebSocket
    user_id: uuid.UUID
    org_id: Optional[uuid.UUID]
    page: Optional[str] = None  # current page/entity for presence


class WSConnectionManager:
    def __init__(self) -> None:
        # user_id -> list of connections (same user, multiple tabs)
        self._connections: dict[uuid.UUID, list[Connection]] = {}

    def _all(self) -> list[Connection]:
        return [c for conns in self._connections.values() for c in conns]

    async def connect(self, conn: Connection) -> None:
        self._connections.setdefault(conn.user_id, []).append(conn)
        await conn.websocket.accept()

    def disconnect(self, conn: Connection) -> None:
        user_conns = self._connections.get(conn.user_id, [])
        if conn in user_conns:
            user_conns.remove(conn)
        if not user_conns:
            self._connections.pop(conn.user_id, None)

    async def send_to_user(self, user_id: uuid.UUID, message: dict) -> None:
        """Send a message to all connections for a specific user."""
        for conn in self._connections.get(user_id, []):
            try:
                await conn.websocket.send_json(message)
            except Exception:
                pass

    async def broadcast_to_org(self, org_id: uuid.UUID, message: dict) -> None:
        """Broadcast a message to all users in an organization."""
        tasks = []
        for conn in self._all():
            if conn.org_id == org_id:
                tasks.append(conn.websocket.send_json(message))
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            _ = results  # swallow exceptions

    def get_presence(self, org_id: uuid.UUID, entity_type: str, entity_id: str) -> list[str]:
        """Return list of user_id strings currently viewing the given entity."""
        key = f"{entity_type}:{entity_id}"
        return [
            str(conn.user_id)
            for conn in self._all()
            if conn.org_id == org_id and conn.page == key
        ]


# Module-level singleton
manager = WSConnectionManager()
