from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from ..config import settings

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть Garant",
                    web_app=WebAppInfo(url=settings.webapp_url),
                )
            ]
        ]
    )
    await message.answer(
        "Добро пожаловать в <b>Garant</b>!\n"
        "Нажмите кнопку ниже, чтобы открыть приложение.",
        reply_markup=kb,
    )
