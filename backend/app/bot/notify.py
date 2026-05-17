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

    Security contract (V5-A-7): ``text`` may contain user-visible
    secrets (PIN reset codes, OTP codes, account-transfer codes) and
    MUST NEVER be logged in plaintext. The current implementation logs
    only the bot configuration state (``logger.warning`` when the bot
    is not configured) and the API failure (``logger.warning`` with the
    ``TelegramAPIError`` message, no body interpolation). Future
    maintainers: do NOT add ``logger.*(..., text)`` or
    ``logger.*(..., extra={"text": text})`` calls to this function or
    to its callers without redacting the text first. If a Sentry SDK
    is ever wired up, configure ``send_default_pii=False`` and disable
    ``LoggingIntegration`` breadcrumb capture for this module so the
    secret cannot leak via breadcrumbs either.

    Returns True on success, False if the bot is not configured or the
    Telegram API rejected the call (e.g. user has not /start'ed the bot).
    """
    bot = get_bot()
    if bot is None:
        # V11-L-15 — structured-logging fields so the JSON-logger
        # downstream (Loki/Sentry) can pivot on event/recipient
        # without regexing the message body. ``text`` is deliberately
        # NOT in ``extra`` per the security contract above.
        logger.warning(
            "Bot is not configured; cannot send DM to %s",
            tg_user_id,
            extra={
                "event": "bot.dm.unconfigured",
                "tg_user_id": tg_user_id,
            },
        )
        return False
    try:
        await bot.send_message(tg_user_id, text)
        return True
    except TelegramAPIError as exc:
        logger.warning(
            "Failed to send DM to %s: %s",
            tg_user_id,
            exc,
            extra={
                "event": "bot.dm.api_error",
                "tg_user_id": tg_user_id,
                "error_class": type(exc).__name__,
            },
        )
        return False
