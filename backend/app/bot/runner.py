from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from ..config import settings
from .handlers import router
from .maintenance import MaintenanceMiddleware

logger = logging.getLogger(__name__)


async def start_polling() -> None:
    if not settings.bot_token or settings.bot_token.startswith("0000"):
        logger.warning("BOT_TOKEN not configured, skipping bot polling")
        return

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.message.outer_middleware(MaintenanceMiddleware())
    dp.callback_query.outer_middleware(MaintenanceMiddleware())
    dp.include_router(router)

    logger.info("Starting aiogram polling...")
    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("Bot polling cancelled")
    except Exception as e:
        logger.error("Bot polling error: %s", e)
