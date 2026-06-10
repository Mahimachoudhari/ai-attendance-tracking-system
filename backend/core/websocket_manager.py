"""
backend/core/websocket_manager.py
----------------------------------
Thread-safe WebSocket connection manager.

• Tracks every connected dashboard client.
• broadcast()  → sends a JSON message to ALL connected clients.
• Automatically removes dead connections on send failure.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket
from loguru import logger


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.append(ws)
        logger.info(f"Dashboard client connected  | total={len(self._clients)}")

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            try:
                self._clients.remove(ws)
            except ValueError:
                pass
        logger.info(f"Dashboard client disconnected | total={len(self._clients)}")

    async def broadcast(self, payload: dict[str, Any]) -> None:
        """Send payload (as JSON) to every connected dashboard client."""
        if not self._clients:
            return

        dead: list[WebSocket] = []

        async with self._lock:
            clients_snapshot = list(self._clients)

        for ws in clients_snapshot:
            try:
                await ws.send_json(payload)
            except Exception as exc:
                logger.debug(f"Dead WS client removed: {exc}")
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    try:
                        self._clients.remove(ws)
                    except ValueError:
                        pass

    @property
    def client_count(self) -> int:
        return len(self._clients)


# Singleton — imported everywhere
manager = ConnectionManager()