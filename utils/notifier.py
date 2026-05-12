"""Single helper for pushing notifications.

Writes a record into the ``Notification`` table, broadcasts to all active
WebSocket subscribers (TMA frontend), and optionally also sends a message
through the aiogram bot so the user gets a push in Telegram itself.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot
from fastapi.concurrency import run_in_threadpool

from utils.database.extras import WebDB
from utils.database.models import Users

logger = logging.getLogger(__name__)


class Notifier:
    """Shared between FastAPI and aiogram."""

    def __init__(self) -> None:
        self._bot: Bot | None = None
        self._subscribers: dict[str, set] = {}
        self._lock = asyncio.Lock()

    def attach_bot(self, bot: Bot) -> None:
        self._bot = bot

    async def subscribe(self, username: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers.setdefault(username.lower(), set()).add(queue)

    async def unsubscribe(self, username: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            subs = self._subscribers.get(username.lower())
            if subs is not None:
                subs.discard(queue)
                if not subs:
                    self._subscribers.pop(username.lower(), None)

    async def push(
        self,
        username: str,
        type_: str,
        title: str,
        body: str = "",
        payload: dict[str, Any] | None = None,
        send_telegram: bool = True,
    ) -> dict:
        """Record + fanout to TMA + optional TG message."""
        notification = await run_in_threadpool(
            WebDB().push_notification, username, type_, title, body, payload
        )

        # WebSocket fanout
        subs = list(self._subscribers.get(username.lower(), set()))
        for q in subs:
            try:
                q.put_nowait({"event": "notification", "data": notification})
            except asyncio.QueueFull:  # pragma: no cover - defensive
                logger.warning("Subscriber queue full for %s", username)

        # Telegram fanout (optional)
        if send_telegram and self._bot is not None:
            user = await run_in_threadpool(Users.get_or_none, Users.username == username.lower())
            if user is not None:
                text = f"<b>{title}</b>"
                if body:
                    text += f"\n\n{body}"
                try:
                    await self._bot.send_message(user.user_id, text)
                except Exception:  # pragma: no cover - tg can fail for many reasons
                    logger.exception("Failed to send TG notification")

        return notification


notifier = Notifier()
