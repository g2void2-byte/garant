"""WebSocket connection manager + optional Redis fan-out (P3.5).

``ConnectionManager`` tracks user → WebSocket(s) maps locally. When
Redis is configured, ``publish`` PUBLISHes a JSON envelope on the
``ws:notifications`` channel and a background ``_listen`` task on every
backend instance pushes the message to its locally-attached sockets.
That gives horizontal-scale fan-out (multiple uvicorn workers /
multiple replicas) without each worker holding every connection.

When Redis is unavailable, ``publish`` falls back to direct local
delivery — the previous in-process behaviour. This means the test
suite, single-process deployments, and the dev loop don't need Redis
running.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

from .redis_client import get_redis

logger = logging.getLogger(__name__)

WS_CHANNEL = "ws:notifications"


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, list[WebSocket]] = {}
        self._pubsub_task: asyncio.Task | None = None
        self._pubsub: Any = None

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(user_id, []).append(websocket)
        logger.info(
            "WS connected: user_id=%d (total=%d)", user_id, len(self._connections.get(user_id, []))
        )

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        conns = self._connections.get(user_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            self._connections.pop(user_id, None)

    async def publish(self, user_id: int, data: dict[str, Any]) -> None:
        """Send to ``user_id``'s sockets, going through Redis if configured.

        With Redis: PUBLISH on ``ws:notifications`` so every backend
        instance forwards to its own local sockets. Without Redis: send
        directly to the local sockets we know about.
        """
        r = await get_redis()
        if r is None:
            await self._send_local(user_id, data)
            return
        envelope = json.dumps({"user_id": user_id, "data": data})
        try:
            await r.publish(WS_CHANNEL, envelope)
        except Exception:  # noqa: BLE001
            logger.exception("WS publish failed; falling back to local delivery")
            await self._send_local(user_id, data)

    # ``send_to_user`` is kept for direct local delivery (used by the
    # pub/sub listener); routers should call ``publish`` instead.
    async def send_to_user(self, user_id: int, data: dict[str, Any]) -> None:
        await self.publish(user_id, data)

    async def _send_local(self, user_id: int, data: dict[str, Any]) -> None:
        conns = self._connections.get(user_id, [])
        dead: list[WebSocket] = []
        payload = json.dumps(data)
        for ws in conns:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(user_id, ws)

    async def start_subscriber(self) -> None:
        """Subscribe to ``ws:notifications`` if Redis is available.

        Idempotent — calling twice does nothing the second time. The
        listener task is cancelled by :meth:`stop_subscriber` during
        application shutdown.
        """
        if self._pubsub_task is not None:
            return
        r = await get_redis()
        if r is None:
            return
        try:
            ps = r.pubsub()
            await ps.subscribe(WS_CHANNEL)
        except Exception:  # noqa: BLE001
            logger.exception("WS subscriber: subscribe failed; staying local-only")
            return
        self._pubsub = ps
        self._pubsub_task = asyncio.create_task(self._listen(ps))

    async def stop_subscriber(self) -> None:
        task = self._pubsub_task
        ps = self._pubsub
        self._pubsub_task = None
        self._pubsub = None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if ps is not None:
            try:
                await ps.unsubscribe(WS_CHANNEL)
                await ps.aclose()
            except Exception:  # noqa: BLE001
                logger.exception("WS subscriber: error during shutdown")

    async def _listen(self, ps: Any) -> None:
        try:
            async for message in ps.listen():
                if message is None or message.get("type") != "message":
                    continue
                try:
                    envelope = json.loads(message["data"])
                    user_id = int(envelope["user_id"])
                    data = envelope["data"]
                except (KeyError, ValueError, TypeError):
                    logger.warning("WS subscriber: malformed envelope %r", message.get("data"))
                    continue
                try:
                    await self._send_local(user_id, data)
                except Exception:  # noqa: BLE001
                    logger.exception("WS subscriber: local dispatch failed")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("WS subscriber: listen loop crashed")


manager = ConnectionManager()
