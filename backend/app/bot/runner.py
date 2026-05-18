from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from ..config import settings
from . import keyboards
from .handlers import router
from .maintenance import MaintenanceMiddleware

logger = logging.getLogger(__name__)


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

    # Loud warning when WEBAPP_URL is not HTTPS: Telegram rejects
    # inline ``web_app=`` buttons with non-HTTPS URLs, which would
    # otherwise make every section button (Поиск / Сделки / Профиль /
    # Помощь) silently look dead. The keyboards module falls back to
    # plain ``url=`` buttons in that case so the bot still answers,
    # but the Mini App won't open inside Telegram until an HTTPS
    # tunnel is set up — flag it so operators see this in logs.
    if not keyboards.webapp_url_is_https():
        logger.warning(
            "WEBAPP_URL is not HTTPS (%s); inline Mini App buttons will fall back to "
            "external url= links. Point WEBAPP_URL at an HTTPS endpoint to launch the "
            "TMA inside Telegram.",
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
