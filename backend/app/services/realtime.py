import asyncio
import json
from typing import Any

from fastapi import WebSocket

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("app.realtime")


class ConnectionManager:
    """Tracks authenticated WebSocket dashboard connections and fan-outs events.

    Single-process implementation; horizontal scaling would swap this for
    Redis pub/sub — documented in docs/architecture.md.
    """

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        return len(self._connections)

    @property
    def max_connections(self) -> int:
        return get_settings().rate_limit_ws_max_connections

    def can_accept(self) -> bool:
        return self.active_count < self.max_connections

    async def reserve(self, conn_id: str) -> bool:
        """Reserve a connection slot (≤ max). Caller must websocket.accept()."""
        async with self._lock:
            if self.active_count >= self.max_connections:
                return False
            self._connections[conn_id] = None  # placeholder until accepted
        return True

    async def register(self, websocket: WebSocket, conn_id: str) -> None:
        async with self._lock:
            self._connections[conn_id] = websocket

    async def disconnect(self, conn_id: str) -> None:
        async with self._lock:
            self._connections.pop(conn_id, None)

    async def send_to(self, conn_id: str, event_type: str, payload: Any) -> None:
        ws = self._connections.get(conn_id)
        if ws is None:
            return
        try:
            await ws.send_text(json.dumps({"type": event_type, "data": payload}, default=str))
        except Exception:  # noqa: BLE001 — a broken socket must not kill the fan-out
            await self.disconnect(conn_id)

    async def broadcast(self, event_type: str, payload: Any) -> None:
        message = json.dumps({"type": event_type, "data": payload}, default=str)
        dead: list[str] = []
        async with self._lock:
            targets = list(self._connections.items())
        for conn_id, ws in targets:
            try:
                await ws.send_text(message)
            except Exception:  # noqa: BLE001
                dead.append(conn_id)
        for conn_id in dead:
            await self.disconnect(conn_id)

    async def heartbeat_loop(self, interval_seconds: float = 20.0) -> None:
        """Keep-alive pings preventing idle proxy disconnects."""
        while True:
            await asyncio.sleep(interval_seconds)
            await self.broadcast("heartbeat", {"ts": asyncio.get_event_loop().time()})


manager = ConnectionManager()
