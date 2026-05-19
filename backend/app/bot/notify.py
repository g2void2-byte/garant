"""Direct Telegram messaging helper.

Used by HTTP routers to push out-of-band messages (e.g. PIN reset codes)
to a user's Telegram DM without going through the polling loop. The bot
instance is created lazily so the app still works when the bot token is
not configured (development / tests).
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup

from ..config import settings

logger = logging.getLogger(__name__)

_bot: Bot | None = None

# 3.2 — one-shot guard for the "bot is not configured" warning. The
# previous behaviour was to emit a fresh ``logger.warning`` on every
# unconfigured ``send_dm`` call, which on dev/test (where
# ``BOT_TOKEN=0000000000:FAKE`` from docker-compose) means a noisy
# warning per notification dispatch — drowning out actual signal in
# logs and Sentry. We emit the warning once per process and downgrade
# subsequent misses to ``debug`` so operators still get a record but
# the steady-state log line stays a single entry. The flag is module-
# local rather than per-bot-instance so re-instantiation (e.g. in
# tests that swap ``settings.bot_token``) re-arms a single fresh
# warning, which matches the operator-facing semantics of "tell me
# the first time something is misconfigured".
_unconfigured_warned: bool = False


def _reset_unconfigured_warned() -> None:
    """Reset the one-shot 'bot not configured' guard.  Test-only hook."""
    global _unconfigured_warned
    _unconfigured_warned = False


def get_bot() -> Bot | None:
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


async def send_dm(
    tg_user_id: int,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
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

    ``reply_markup`` is an optional inline keyboard (typically a "view
    deal" / "view deposit" deep-link button) attached to the DM. It is
    passed through to ``Bot.send_message`` unchanged. ``None`` (the
    default) sends a plain text DM, preserving the historical
    behaviour for callers that haven't been migrated.

    Returns True on success, False if the bot is not configured or the
    Telegram API rejected the call (e.g. user has not /start'ed the bot).
    """
    bot = get_bot()
    if bot is None:
        # V11-L-15 — structured-logging fields so the JSON-logger
        # downstream (Loki/Sentry) can pivot on event/recipient
        # without regexing the message body. ``text`` is deliberately
        # NOT in ``extra`` per the security contract above.
        #
        # 3.2 — one-shot ``warning`` then ``debug``-level for the
        # rest of the process lifetime. See the
        # ``_unconfigured_warned`` comment above for the rationale.
        # We do NOT use ``logger.warning(..., stack_info=once)`` here
        # because the dispatch decision is driven by a process-wide
        # boolean, not by the logger's own dedup machinery — so the
        # behaviour is identical regardless of which logging backend
        # (stdlib / structlog / json-logger) is wired up.
        global _unconfigured_warned
        level = logging.WARNING if not _unconfigured_warned else logging.DEBUG
        logger.log(
            level,
            "Bot is not configured; cannot send DM to %s",
            tg_user_id,
            extra={
                "event": "bot.dm.unconfigured",
                "tg_user_id": tg_user_id,
                "first_observation": not _unconfigured_warned,
            },
        )
        _unconfigured_warned = True
        return False
    try:
        await bot.send_message(tg_user_id, text, reply_markup=reply_markup)
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
