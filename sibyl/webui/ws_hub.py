"""Thread-safe WebSocket connection hub with per-project fan-out."""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class WSHub:
    """Thread-safe WebSocket connection registry with per-channel fan-out."""

    def __init__(self):
        self._clients: dict[str, set[Any]] = defaultdict(set)
        self._lock = threading.Lock()

    def register(self, channel: str, ws: Any) -> None:
        with self._lock:
            self._clients[channel].add(ws)

    def unregister(self, channel: str, ws: Any) -> None:
        with self._lock:
            clients = self._clients.get(channel)
            if clients is None:
                return
            clients.discard(ws)
            if not clients:
                self._clients.pop(channel, None)

    def client_count(self, channel: str) -> int:
        with self._lock:
            return len(self._clients.get(channel, set()))

    def broadcast_sync(self, channel: str, message: dict[str, Any]) -> None:
        payload = json.dumps(message, ensure_ascii=False, default=str)
        with self._lock:
            clients = list(self._clients.get(channel, set()))

        dead: list[Any] = []
        for ws in clients:
            try:
                ws.send(payload)
            except Exception:
                dead.append(ws)

        if dead:
            with self._lock:
                remaining = self._clients.get(channel)
                if remaining is None:
                    return
                for ws in dead:
                    remaining.discard(ws)
                    logger.debug("Removed dead WebSocket connection for %s", channel)
                if not remaining:
                    self._clients.pop(channel, None)

    def broadcast_all_sync(self, message: dict[str, Any]) -> None:
        with self._lock:
            channels = list(self._clients)
        for channel in channels:
            self.broadcast_sync(channel, message)
