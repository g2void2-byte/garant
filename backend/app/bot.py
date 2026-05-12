"""aiogram bot — runs alongside FastAPI in long-polling mode."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from .config import settings
from .database import SessionLocal
from .services import commission_percent, welcome_message

log = logging.getLogger(__name__)


def _main_menu() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="💼 Сделки"), KeyboardButton(text="💵 Баланс")],
        [KeyboardButton(text="🔍 Поиск"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="❓ Помощь"), KeyboardButton(text="🛟 Поддержка")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def _miniapp_button(text: str = "🚀 Открыть AutoGarant", path: str = "") -> InlineKeyboardMarkup:
    url = settings.webapp_url.rstrip("/") + (f"/{path.lstrip('/')}" if path else "")
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))]]
    )


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def on_start(msg: Message) -> None:
        async with SessionLocal() as session:
            percent = await commission_percent(session)
            template = await welcome_message(session)
        text = template.format(commission=f"{percent:g}")
        await msg.answer(text, reply_markup=_main_menu())
        await msg.answer("Откройте AutoGarant одним нажатием:", reply_markup=_miniapp_button())

    @dp.message(Command("help"))
    @dp.message(F.text == "❓ Помощь")
    async def on_help(msg: Message) -> None:
        await msg.answer(
            "ℹ️ <b>Как это работает</b>\n\n"
            "1. Создайте сделку, указав контрагента и сумму.\n"
            "2. Покупатель оплачивает — деньги замораживаются в эскроу.\n"
            "3. После получения товара/услуги покупатель подтверждает сделку.\n"
            "4. Продавец получает оплату за вычетом комиссии сервиса.\n\n"
            "При споре подключается арбитр AutoGarant.",
            reply_markup=_miniapp_button("📖 Открыть приложение"),
        )

    @dp.message(F.text == "💼 Сделки")
    async def on_deals(msg: Message) -> None:
        await msg.answer("Список сделок:", reply_markup=_miniapp_button("📁 Открыть сделки", "deals"))

    @dp.message(F.text == "💵 Баланс")
    async def on_balance(msg: Message) -> None:
        await msg.answer("Ваш баланс:", reply_markup=_miniapp_button("💰 Открыть баланс", "balance"))

    @dp.message(F.text == "🔍 Поиск")
    async def on_search(msg: Message) -> None:
        await msg.answer("Поиск участников:", reply_markup=_miniapp_button("🔎 Найти", "search"))

    @dp.message(F.text == "👤 Профиль")
    async def on_profile(msg: Message) -> None:
        await msg.answer("Ваш профиль:", reply_markup=_miniapp_button("👤 Открыть профиль", "profile"))

    @dp.message(F.text == "🛟 Поддержка")
    async def on_support(msg: Message) -> None:
        await msg.answer(
            "✉️ По любым вопросам пишите в поддержку: @AutoGarantSupport",
        )

    return dp


async def run_bot() -> None:
    if not settings.bot_token or settings.disable_bot:
        log.warning("Bot disabled (no BOT_TOKEN or DISABLE_BOT=1). Skipping polling.")
        # Keep the task alive so cancellation works cleanly.
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            return

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = create_dispatcher()
    log.info("Starting Telegram bot polling…")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
