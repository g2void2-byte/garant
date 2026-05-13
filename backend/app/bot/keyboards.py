"""Inline + reply keyboards for the bot menu (P3.2)."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from ..config import settings
from ..models import User

# ── Reply keyboard (persistent bottom bar) ─────────────────────────────────

SEARCH_BUTTON = "🔎 Поиск"
DEALS_BUTTON = "📁 Сделки"
PROFILE_BUTTON = "👤 Профиль"
HELP_BUTTON = "⚙ Помощь"

# Callback data prefixes — kept short to fit Telegram's 64-byte cap.
CB_PROFILE = "bot:profile"
CB_SETTINGS = "bot:settings"
CB_TOGGLE_ANON = "bot:tog:anon"
CB_TOGGLE_HIDDEN = "bot:tog:hidden"


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=SEARCH_BUTTON), KeyboardButton(text=DEALS_BUTTON)],
            [KeyboardButton(text=PROFILE_BUTTON), KeyboardButton(text=HELP_BUTTON)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def _webapp(url_path: str) -> WebAppInfo:
    """Build a WebAppInfo pointing at the configured TMA + optional path."""
    base = settings.webapp_url.rstrip("/")
    suffix = url_path if url_path.startswith("/") else "/" + url_path
    return WebAppInfo(url=base + suffix)


# ── Section keyboards ─────────────────────────────────────────────────────


def search_keyboard() -> InlineKeyboardMarkup:
    # "Поиск пользователя" opens the user-search hub; "Поиск услуг" opens
    # the categories grid which is the entry point for service search.
    # The TMA does not consume query strings here, so we use bare routes.
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🥷 Поиск пользователя", web_app=_webapp("/search"))],
            [InlineKeyboardButton(text="🛒 Поиск услуг", web_app=_webapp("/search/categories"))],
        ]
    )


def deals_keyboard(
    *, buys_count: int, sales_count: int, pending_payment_count: int
) -> InlineKeyboardMarkup:
    # The deals list inside the TMA filters by role/status via in-page
    # tabs — it does not consume query strings. All three buttons open
    # /deals; counts in the labels are informational.
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🛒 Покупок: {buys_count}",
                    web_app=_webapp("/deals"),
                ),
                InlineKeyboardButton(
                    text=f"🎁 Продаж: {sales_count}",
                    web_app=_webapp("/deals"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"⏰ Ожидающие оплаты: {pending_payment_count}",
                    web_app=_webapp("/deals"),
                )
            ],
        ]
    )


def profile_keyboard() -> InlineKeyboardMarkup:
    second_row: list[InlineKeyboardButton] = []
    if settings.bot_forums_url:
        second_row.append(InlineKeyboardButton(text="🏛 Форумы", url=settings.bot_forums_url))
    second_row.append(InlineKeyboardButton(text="⚙ Настройки", callback_data=CB_SETTINGS))

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Мой профиль", web_app=_webapp("/profile"))],
            second_row,
            [InlineKeyboardButton(text="💼 Депозит", web_app=_webapp("/deposit"))],
        ]
    )


def settings_keyboard(user: User) -> InlineKeyboardMarkup:
    anon_mark = "✅" if user.is_anonymous_deals else "❌"
    hidden_mark = "✅" if user.is_hidden_profile else "❌"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{anon_mark} Анонимность при сделках", callback_data=CB_TOGGLE_ANON
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{hidden_mark} Скрытый профиль", callback_data=CB_TOGGLE_HIDDEN
                )
            ],
            # The TMA has no dedicated PIN settings page — the global
            # PinGate shows a setup/unlock dialog on any protected route,
            # so we route to /profile and let the gate take over.
            [InlineKeyboardButton(text="🔒 PIN", web_app=_webapp("/profile"))],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=CB_PROFILE)],
        ]
    )


def help_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if settings.bot_docs_url:
        rows.append([InlineKeyboardButton(text="📖 Инструкция", url=settings.bot_docs_url)])
    if settings.bot_community_chat_url:
        rows.append([InlineKeyboardButton(text="💬 Наш чат", url=settings.bot_community_chat_url)])
    if settings.bot_arbitration_url:
        rows.append([InlineKeyboardButton(text="⚖ Арбитраж", url=settings.bot_arbitration_url)])
    if settings.bot_support_username:
        uname = settings.bot_support_username.lstrip("@")
        rows.append([InlineKeyboardButton(text="👤 Помощь", url=f"https://t.me/{uname}")])
    # Always offer a way back to the TMA if everything else is empty.
    if not rows:
        rows.append([InlineKeyboardButton(text="🪄 Открыть приложение", web_app=_webapp("/"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)
