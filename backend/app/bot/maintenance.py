"""Bot-side maintenance gate.

Mirrors :mod:`backend.app.maintenance` for the FastAPI side: when
``app_settings.maintenance_enabled`` is ``True``, every incoming
message / callback is answered with the configured maintenance message
instead of being routed to the normal handlers. The ``/start`` command
still works so users can pull a fresh status, and we short-circuit
before any DB-mutation handler runs.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy import select

from ..db import async_session
from ..models import AppSettings

logger = logging.getLogger(__name__)

_DEFAULT_MESSAGE = "Сервис на технических работах. Повторите позже."


async def _maintenance_payload() -> tuple[bool, str]:
    try:
        async with async_session() as session:
            row = (
                await session.execute(select(AppSettings).order_by(AppSettings.id).limit(1))
            ).scalar_one_or_none()
    except Exception:  # noqa: BLE001
        # V11-L-15 — structured-logging fields so the JSON-logger
        # downstream (Loki/Sentry) can pivot on event without
        # regexing the message body. ``error_class`` lets us track
        # the underlying DB failure mode (timeout vs auth vs ...).
        logger.exception(
            "bot maintenance: settings lookup failed",
            extra={"event": "bot.maintenance.settings_lookup_failed"},
        )
        return False, _DEFAULT_MESSAGE
    if row is None or not row.maintenance_enabled:
        return False, _DEFAULT_MESSAGE
    return True, row.maintenance_message or _DEFAULT_MESSAGE


class MaintenanceMiddleware(BaseMiddleware):
    """Short-circuit every update with the maintenance message when enabled."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        enabled, message = await _maintenance_payload()
        if not enabled:
            return await handler(event, data)

        if isinstance(event, Message):
            await event.answer(message)
            return None
        if isinstance(event, CallbackQuery):
            await event.answer(message, show_alert=True)
            return None
        # Unknown update type — drop silently.
        return None
