from __future__ import annotations

import asyncio
from typing import Any


class WebSocketManager:
    def __init__(self):
        self.connections: set[Any] = set()
        self._lock = asyncio.Lock()

    async def add(self, websocket: Any) -> None:
        async with self._lock:
            self.connections.add(websocket)

    async def remove(self, websocket: Any) -> None:
        async with self._lock:
            self.connections.discard(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        async with self._lock:
            connections = tuple(self.connections)
        stale = []
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception:
                stale.append(websocket)
        if stale:
            async with self._lock:
                for websocket in stale:
                    self.connections.discard(websocket)
