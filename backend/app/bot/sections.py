"""Data-loading + render helpers for each bot menu section (P3.2).

Each public ``send_<section>`` function:
  1. fetches/upserts the ``User`` row for the given Telegram id,
  2. queries section-specific stats from the DB,
  3. calls ``answer_method`` (a callable like ``message.answer_photo`` or
     ``callback.message.edit_text``) with the rendered text + keyboard.

Bot handlers stay thin — they just decide which section to dispatch to.
"""

from __future__ import annotations

import pathlib

from aiogram.types import (
    BufferedInputFile,
    FSInputFile,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import async_session
from ..models import Deal, DealStatus, User
from . import banners, keyboards, texts

# Section-specific banner images. Drop a PNG/JPG next to this file under
# ``assets/`` (search.png, deals.png, profile.png, help.png) and the bot
# will automatically attach it. Missing files are silently fine — the
# handler falls back to a text-only message.
_ASSETS_DIR = pathlib.Path(__file__).parent / "assets"


def _static_banner(name: str) -> FSInputFile | None:
    for ext in ("png", "jpg", "jpeg", "webp"):
        path = _ASSETS_DIR / f"{name}.{ext}"
        if path.exists():
            return FSInputFile(path)
    return None


# ── User lookup ───────────────────────────────────────────────────────────


async def _get_or_create_user(
    session: AsyncSession, tg_user_id: int, *, username: str | None, first_name: str | None
) -> User:
    user = (
        await session.execute(select(User).where(User.tg_user_id == tg_user_id))
    ).scalar_one_or_none()
    if user is not None:
        # Keep cached username/display_name fresh — same logic as deps.get_current_user.
        changed = False
        if username and user.username != username:
            user.username = username
            changed = True
        if first_name and not user.display_name:
            user.display_name = first_name
            changed = True
        if changed:
            await session.commit()
            await session.refresh(user)
        return user

    user = User(
        tg_user_id=tg_user_id,
        username=username,
        display_name=first_name or "",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


# ── Stats ─────────────────────────────────────────────────────────────────


async def _deals_stats(session: AsyncSession, user_id: int) -> dict[str, float | int]:
    """Aggregate counts/volume for the user's deal history.

    Counts every deal the user participates in (buyer OR seller). The
    "volume" is the sum of ``Deal.sum`` across completed deals only.
    """
    total_count = (
        await session.execute(
            select(func.count(Deal.id)).where(
                or_(Deal.buyer_id == user_id, Deal.seller_id == user_id)
            )
        )
    ).scalar_one()

    buys_count = (
        await session.execute(
            select(func.count(Deal.id)).where(
                Deal.buyer_id == user_id, Deal.status == DealStatus.completed
            )
        )
    ).scalar_one()
    buys_sum = (
        await session.execute(
            select(func.coalesce(func.sum(Deal.sum), 0)).where(
                Deal.buyer_id == user_id, Deal.status == DealStatus.completed
            )
        )
    ).scalar_one()

    sales_count = (
        await session.execute(
            select(func.count(Deal.id)).where(
                Deal.seller_id == user_id, Deal.status == DealStatus.completed
            )
        )
    ).scalar_one()
    sales_sum = (
        await session.execute(
            select(func.coalesce(func.sum(Deal.sum), 0)).where(
                Deal.seller_id == user_id, Deal.status == DealStatus.completed
            )
        )
    ).scalar_one()

    pending_payment_count = (
        await session.execute(
            select(func.count(Deal.id)).where(
                or_(Deal.buyer_id == user_id, Deal.seller_id == user_id),
                Deal.status.in_((DealStatus.pending_confirmation, DealStatus.pending_payment)),
            )
        )
    ).scalar_one()

    return {
        "total_count": int(total_count),
        "buys_count": int(buys_count),
        "buys_sum": float(buys_sum or 0),
        "sales_count": int(sales_count),
        "sales_sum": float(sales_sum or 0),
        "pending_payment_count": int(pending_payment_count),
        "total_volume": float((buys_sum or 0) + (sales_sum or 0)),
    }


# ── Public senders ────────────────────────────────────────────────────────


async def _send(
    message: Message,
    text: str,
    *,
    keyboard: InlineKeyboardMarkup,
    photo: FSInputFile | BufferedInputFile | None,
) -> None:
    if photo is not None:
        await message.answer_photo(photo=photo, caption=text, reply_markup=keyboard)
    else:
        await message.answer(text, reply_markup=keyboard)


async def send_search(message: Message) -> None:
    await _send(
        message,
        texts.search_caption(),
        keyboard=keyboards.search_keyboard(),
        photo=_static_banner("search"),
    )


async def send_deals(
    message: Message, *, tg_user_id: int, username: str | None, first_name: str | None
) -> None:
    async with async_session() as session:
        user = await _get_or_create_user(
            session, tg_user_id, username=username, first_name=first_name
        )
        stats = await _deals_stats(session, user.id)

    body = texts.deals_summary(
        total_volume=stats["total_volume"],
        total_count=stats["total_count"],
        buys_count=stats["buys_count"],
        sales_count=stats["sales_count"],
        pending_payment_count=stats["pending_payment_count"],
    )
    kb = keyboards.deals_keyboard(
        buys_count=stats["buys_count"],
        sales_count=stats["sales_count"],
        pending_payment_count=stats["pending_payment_count"],
    )
    photo = BufferedInputFile(
        banners.render_deals(
            total_volume=stats["total_volume"],
            deal_count=stats["total_count"],
            sale_count=stats["sales_count"],
        ),
        filename="deals.jpg",
    )
    await _send(message, body, keyboard=kb, photo=photo)


async def send_profile(
    message: Message, *, tg_user_id: int, username: str | None, first_name: str | None
) -> None:
    async with async_session() as session:
        user = await _get_or_create_user(
            session, tg_user_id, username=username, first_name=first_name
        )
        stats = await _deals_stats(session, user.id)

    body = texts.profile_summary(
        user,
        buys_count=stats["buys_count"],
        buys_sum=stats["buys_sum"],
        sales_count=stats["sales_count"],
        sales_sum=stats["sales_sum"],
    )
    photo = BufferedInputFile(
        banners.render_profile(username=user.username, deposit=float(user.balance or 0)),
        filename="profile.jpg",
    )
    await _send(message, body, keyboard=keyboards.profile_keyboard(), photo=photo)


async def send_help(message: Message) -> None:
    await _send(
        message,
        texts.help_caption(),
        keyboard=keyboards.help_keyboard(),
        photo=_static_banner("help"),
    )


# ── Settings sub-menu (toggle handlers) ───────────────────────────────────


async def render_settings(user: User) -> tuple[str, InlineKeyboardMarkup]:
    return texts.settings_summary(user), keyboards.settings_keyboard(user)


async def _load_user(session: AsyncSession, tg_user_id: int) -> User:
    """Fetch the user row, falling back to a fresh upsert when missing.

    Callback queries can fire before the user has interacted with /start
    (rare but possible if Telegram replays a stale callback), so we
    never raise on a missing row — we create a minimal user record so
    the handler can keep going.
    """
    user = (
        await session.execute(select(User).where(User.tg_user_id == tg_user_id))
    ).scalar_one_or_none()
    if user is not None:
        return user
    user = User(tg_user_id=tg_user_id, username=None, display_name="")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def toggle_anonymous(tg_user_id: int) -> User:
    async with async_session() as session:
        user = await _load_user(session, tg_user_id)
        user.is_anonymous_deals = not user.is_anonymous_deals
        await session.commit()
        await session.refresh(user)
        return user


async def toggle_hidden(tg_user_id: int) -> User:
    async with async_session() as session:
        user = await _load_user(session, tg_user_id)
        user.is_hidden_profile = not user.is_hidden_profile
        await session.commit()
        await session.refresh(user)
        return user


async def load_user(tg_user_id: int) -> User:
    async with async_session() as session:
        return await _load_user(session, tg_user_id)


async def load_profile_payload(tg_user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    async with async_session() as session:
        user = await _load_user(session, tg_user_id)
        stats = await _deals_stats(session, user.id)
    body = texts.profile_summary(
        user,
        buys_count=stats["buys_count"],
        buys_sum=stats["buys_sum"],
        sales_count=stats["sales_count"],
        sales_sum=stats["sales_sum"],
    )
    return body, keyboards.profile_keyboard()
