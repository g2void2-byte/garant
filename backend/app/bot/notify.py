"""Direct Telegram messaging helper.

Used by HTTP routers to push out-of-band messages (e.g. PIN reset codes)
to a user's Telegram DM without going through the polling loop. The bot
instance is created lazily so the app still works when the bot token is
not configured (development / tests).
"""

from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from ..config import settings

logger = logging.getLogger(__name__)

_bot: Optional[Bot] = None


def get_bot() -> Optional[Bot]:
    global _bot
    if _bot is not None:
        return _bot
    if not settings.bot_token:
        return None
    _bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    return _bot


async def send_dm(tg_user_id: int, text: str) -> bool:
    """Send an HTML-formatted DM to the given Telegram user.

    Returns True on success, False if the bot is not configured or the
    Telegram API rejected the call (e.g. user has not /start'ed the bot).
    """
    bot = get_bot()
    if bot is None:
        logger.warning("Bot is not configured; cannot send DM to %s", tg_user_id)
        return False
    try:
        await bot.send_message(tg_user_id, text)
        return True
    except TelegramAPIError as exc:
        logger.warning("Failed to send DM to %s: %s", tg_user_id, exc)
        return False
