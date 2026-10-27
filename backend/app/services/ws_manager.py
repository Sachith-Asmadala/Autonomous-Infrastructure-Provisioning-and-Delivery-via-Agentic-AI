"""
WebSocket connection manager.

Responsibilities
----------------
- Tracks all open WebSocket connections per user.
- Enforces a per-user connection limit (default: 5).
- Provides a heartbeat / ping-pong loop so stale connections are detected.
- Exposes ``broadcast_to_user()`` for server-initiated messages (e.g. HITL
  notifications pushed to the reviewer who can decide an approval).
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Maximum concurrent WebSocket connections per user_id
MAX_CONNECTIONS_PER_USER = 5

# Seconds between server-side ping frames
HEARTBEAT_INTERVAL = 30


class ConnectionManager:
    """Thread-safe (asyncio-safe) WebSocket registry."""

    def __init__(self) -> None:
        # user_id → list[WebSocket]
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        self._lock = asyncio.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self, websocket: WebSocket, user_id: str) -> bool:
        """
        Accept and register a WebSocket connection.

        Returns False (and closes the socket with 4008) if the user already
        has MAX_CONNECTIONS_PER_USER open connections.
        """
        async with self._lock:
            existing = self._connections[user_id]
            if len(existing) >= MAX_CONNECTIONS_PER_USER:
                await websocket.close(
                    code=4008,
                    reason=f"Too many connections (max {MAX_CONNECTIONS_PER_USER} per user).",
                )
                return False
            await websocket.accept()
            existing.append(websocket)
            logger.info("ws.connected user=%s total=%d", user_id, len(existing))
            return True

    async def disconnect(self, websocket: WebSocket, user_id: str) -> None:
        async with self._lock:
            sockets = self._connections.get(user_id, [])
            if websocket in sockets:
                sockets.remove(websocket)
            if not sockets:
                self._connections.pop(user_id, None)
        logger.info("ws.disconnected user=%s", user_id)

    # ── Messaging ─────────────────────────────────────────────────────────────

    async def send_text(self, websocket: WebSocket, text: str) -> None:
        try:
            await websocket.send_text(text)
        except Exception:
            pass  # handled by the caller's disconnect logic

    async def send_json(self, websocket: WebSocket, data: dict) -> None:
        try:
            await websocket.send_json(data)
        except Exception:
            pass

    async def broadcast_to_user(self, user_id: str, data: dict) -> None:
        """Push a JSON message to all open connections for a user."""
        async with self._lock:
            sockets = list(self._connections.get(user_id, []))
        for ws in sockets:
            await self.send_json(ws, data)

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    async def heartbeat_loop(self, websocket: WebSocket, user_id: str) -> None:
        """
        Run until the connection is gone.  Sends a ping every
        HEARTBEAT_INTERVAL seconds; cleans up on any failure.
        """
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await websocket.send_json({"event": "ping"})
        except Exception:
            await self.disconnect(websocket, user_id)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def active_count(self, user_id: str) -> int:
        return len(self._connections.get(user_id, []))

    def total_connections(self) -> int:
        return sum(len(v) for v in self._connections.values())


# Singleton — import this everywhere
manager = ConnectionManager()
