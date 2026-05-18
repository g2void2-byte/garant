from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent

from ..config import settings
from . import keyboards
from .handlers import router
from .maintenance import MaintenanceMiddleware

logger = logging.getLogger(__name__)


async def _on_dispatcher_error(event: ErrorEvent) -> bool:
    """Top-level aiogram error handler.

    Without this, handler exceptions are logged by aiogram only at its
    own ``aiogram.event`` logger, which the project's runtime log
    config (alembic's ``fileConfig`` sets the root level to ``WARN`` /
    sometimes silences non-alembic loggers entirely) was filtering out.
    The result: in production the bot looked dead on section taps and
    no trace was ever written. We now log at ERROR with the dispatcher's
    update id + the failing handler exception so this class of bug can
    never silently regress again.
    """
    update = event.update
    update_id = getattr(update, "update_id", None)
    exc = event.exception
    logger.error(
        "bot handler error on update_id=%s: %s: %s",
        update_id,
        type(exc).__name__,
        exc,
        exc_info=exc,
        extra={
            "event": "bot.handler.exception",
            "update_id": update_id,
            "error_class": type(exc).__name__,
        },
    )
    # Signal aiogram that the error has been handled and not to re-raise
    # — re-raising would tear down ``start_polling`` for the whole bot.
    return True


async def start_polling() -> None:
    # V11-L-15 — structured-logging fields so the JSON-logger
    # downstream (Loki/Sentry) can pivot on event without
    # regexing the message body. ``BOT_TOKEN`` is deliberately
    # NOT in ``extra`` (token literal) — only the configured/
    # placeholder shape is captured.
    if not settings.bot_token or settings.bot_token.startswith("0000"):
        logger.warning(
            "BOT_TOKEN not configured, skipping bot polling",
            extra={"event": "bot.polling.unconfigured"},
        )
        return

    # Loud warning when WEBAPP_URL is not HTTPS: Telegram rejects both
    # ``web_app=http://...`` (BUTTON_TYPE_INVALID) and
    # ``url=http://localhost/...`` (Wrong HTTP URL), so every section
    # button (Поиск / Сделки / Профиль / Помощь) would silently look
    # dead. The keyboards module now falls back to ``callback_data=``
    # buttons that always render and show a diagnostic alert when
    # tapped — flag this here so operators see in logs that the Mini
    # App will not open inside Telegram until an HTTPS endpoint is
    # configured.
    if not keyboards.webapp_url_is_https():
        logger.warning(
            "WEBAPP_URL is not HTTPS (%s); inline Mini App buttons will be inert and "
            "only show a 'configure HTTPS' alert when tapped. Point WEBAPP_URL at an "
            "HTTPS endpoint to launch the TMA inside Telegram.",
            settings.webapp_url,
            extra={
                "event": "bot.polling.webapp_url_not_https",
                "webapp_url": settings.webapp_url,
            },
        )

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.message.outer_middleware(MaintenanceMiddleware())
    dp.callback_query.outer_middleware(MaintenanceMiddleware())
    dp.include_router(router)
    dp.errors.register(_on_dispatcher_error)

    logger.info(
        "Starting aiogram polling...",
        extra={"event": "bot.polling.start"},
    )
    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logger.info(
            "Bot polling cancelled",
            extra={"event": "bot.polling.cancelled"},
        )
    except Exception as e:
        logger.error(
            "Bot polling error: %s",
            e,
            exc_info=True,
            extra={
                "event": "bot.polling.unexpected_exception",
                "error_class": type(e).__name__,
            },
        )
