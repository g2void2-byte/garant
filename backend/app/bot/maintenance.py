"""Bot-side maintenance gate.

Mirrors :mod:`backend.app.maintenance` for the FastAPI side: when
``app_settings.maintenance_enabled`` is ``True``, every incoming
message / callback is answered with the configured maintenance message
instead of being routed to the normal handlers. The ``/start`` command
still works so users can pull a fresh status, and we short-circuit
before any DB-mutation handler runs.

INFO #3 — both the bot middleware and the public
``GET /api/settings/maintenance`` probe now go through the cached
``maintenance._get_maintenance`` helper. Pre-fix each bot update
opened a fresh DB session and re-read ``app_settings``; under a
busy bot that's one extra round-trip per message even when the flag
hasn't changed. The 5-second in-process TTL is the same one used by
the HTTP middleware (``backend.app.maintenance._TTL_SECONDS``); a
toggle made via the admin panel calls ``invalidate_cache()`` and is
reflected on the same worker immediately.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from ..maintenance import _get_maintenance

logger = logging.getLogger(__name__)

_DEFAULT_MESSAGE = "Сервис на технических работах. Повторите позже."


async def _maintenance_payload() -> tuple[bool, str]:
    try:
        enabled, message = await _get_maintenance()
    except Exception:  # noqa: BLE001
        # ``_get_maintenance`` already throttles its own
        # DB-lookup-failed logs (see ``_log_db_lookup_failure``).
        # We still surface a defensive ``logger.exception`` here so
        # the bot-side error path keeps a structured event the
        # operator can pivot on independently from the HTTP-side one.
        logger.exception(
            "bot maintenance: settings lookup failed",
            extra={"event": "bot.maintenance.settings_lookup_failed"},
        )
        return False, _DEFAULT_MESSAGE
    if not enabled:
        return False, _DEFAULT_MESSAGE
    return True, message or _DEFAULT_MESSAGE


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
