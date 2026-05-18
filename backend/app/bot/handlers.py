"""Aiogram dispatch for the P3.2 bot menu.

Routing layout:
  * ``/start`` — greet + send the persistent reply keyboard.
  * Reply-keyboard text (🔎 Поиск / 📁 Сделки / 👤 Профиль / ⚙ Помощь) — each
    handler builds a fresh message with the appropriate inline keyboard.
  * Settings submenu — driven by callback queries with ``bot:`` prefix so
    we can keep responses scoped to the message being edited.

Data work happens inside :mod:`backend.app.bot.sections`; this module
only does routing + filter wiring.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from . import keyboards, sections

logger = logging.getLogger(__name__)

router = Router()


# ── /start ───────────────────────────────────────────────────────────────


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        sections.texts.WELCOME,
        reply_markup=keyboards.main_reply_keyboard(),
    )


# ── Reply-keyboard buttons (exact text match) ────────────────────────────


def _user_kwargs(message: Message) -> dict[str, object]:
    if message.from_user is None:
        # Bot updates without a user (channel posts) are not relevant here.
        return {"tg_user_id": 0, "username": None, "first_name": None}
    return {
        "tg_user_id": message.from_user.id,
        "username": message.from_user.username,
        "first_name": message.from_user.first_name,
    }


@router.message(F.text.in_(keyboards.SEARCH_BUTTON_TEXTS))
async def on_search(message: Message) -> None:
    await sections.send_search(message)


@router.message(F.text.in_(keyboards.DEALS_BUTTON_TEXTS))
async def on_deals(message: Message) -> None:
    await sections.send_deals(message, **_user_kwargs(message))


@router.message(F.text.in_(keyboards.PROFILE_BUTTON_TEXTS))
async def on_profile(message: Message) -> None:
    await sections.send_profile(message, **_user_kwargs(message))


@router.message(F.text.in_(keyboards.HELP_BUTTON_TEXTS))
async def on_help(message: Message) -> None:
    await sections.send_help(message)


# ── Settings submenu (inline callbacks) ──────────────────────────────────


async def _replace_body(callback: CallbackQuery, body: str, kb) -> None:
    """Edit the message in-place — caption for photo messages, text otherwise."""
    message = callback.message
    if message is None:
        return
    if message.photo:
        await message.edit_caption(caption=body, reply_markup=kb)
    else:
        await message.edit_text(body, reply_markup=kb)


@router.callback_query(F.data == keyboards.CB_SETTINGS)
async def cb_settings(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer()
        return
    user = await sections.load_user(callback.from_user.id)
    body, kb = await sections.render_settings(user)
    await _replace_body(callback, body, kb)
    await callback.answer()


@router.callback_query(F.data == keyboards.CB_PROFILE)
async def cb_back_to_profile(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer()
        return
    body, kb = await sections.load_profile_payload(callback.from_user.id)
    await _replace_body(callback, body, kb)
    await callback.answer()


@router.callback_query(F.data == keyboards.CB_TOGGLE_ANON)
async def cb_toggle_anon(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer()
        return
    user = await sections.toggle_anonymous(callback.from_user.id)
    body, kb = await sections.render_settings(user)
    await _replace_body(callback, body, kb)
    status = "включена" if user.is_anonymous_deals else "выключена"
    await callback.answer(f"Анонимность при сделках {status}")


@router.callback_query(F.data == keyboards.CB_TOGGLE_HIDDEN)
async def cb_toggle_hidden(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer()
        return
    user = await sections.toggle_hidden(callback.from_user.id)
    body, kb = await sections.render_settings(user)
    await _replace_body(callback, body, kb)
    status = "включён" if user.is_hidden_profile else "выключен"
    await callback.answer(f"Скрытый профиль {status}")


# Tapped when the bot is running with a non-HTTPS ``WEBAPP_URL`` and the
# Mini App button has been replaced with a ``callback_data=`` button by
# :func:`backend.app.bot.keyboards._webapp_button`. The contract is:
# the section message always reaches the user (no silent
# ``BUTTON_TYPE_INVALID`` / ``Wrong HTTP URL`` drop), and tapping any of
# the Mini App buttons gets a single explicit diagnostic — including
# which TMA path the user wanted — instead of opening nothing.
@router.callback_query(F.data.startswith(keyboards.CB_TMA_UNAVAILABLE_PREFIX))
async def cb_tma_unavailable(callback: CallbackQuery) -> None:
    await callback.answer(
        "Мини-приложение пока недоступно: WEBAPP_URL должен быть публичным "
        "HTTPS-адресом. Сообщите администратору, чтобы он подключил HTTPS-туннель "
        "или боевой домен.",
        show_alert=True,
    )


# ── Forensic fallback ────────────────────────────────────────────────────


# Any text message that did NOT match a section button lands here. We log
# the raw text + hex so a stuck reply-keyboard tap (e.g. emoji-variant
# mismatch, client-side normalisation) leaves a paper trail instead of
# silently being dropped on the floor. The bot intentionally stays
# silent — answering every random user message would be noisy.
@router.message(F.text)
async def _on_unmatched_text(message: Message) -> None:
    text = message.text or ""
    logger.warning(
        "bot: dropping unmatched text message",
        extra={
            "event": "bot.unmatched_text",
            "text": text,
            "text_hex": text.encode("utf-8").hex(),
            "text_len": len(text),
            "from_username": message.from_user.username if message.from_user else None,
            "from_id": message.from_user.id if message.from_user else None,
        },
    )
