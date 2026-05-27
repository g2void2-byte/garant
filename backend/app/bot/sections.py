"""Data-loading + render helpers for each bot menu section (P3.2).

Each public ``send_<section>`` function:
  1. fetches/upserts the ``User`` row for the given Telegram id,
  2. queries section-specific stats from the DB,
  3. calls ``answer_method`` (a callable like ``message.answer_photo`` or
     ``callback.message.edit_text``) with the rendered text + keyboard.

Bot handlers stay thin — they just decide which section to dispatch to.
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any

from aiogram.types import (
    BufferedInputFile,
    FSInputFile,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import async_session
from ..models import Currency, Deal, DealStatus, User
from . import banners, keyboards, texts

logger = logging.getLogger(__name__)

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
    """Return the ``User`` for ``tg_user_id``, inserting one if missing.

    M-4 — two concurrent Telegram callbacks from the same user can hit
    this function at the same time; the old check-then-insert pattern
    raced and one of them bubbled an ``IntegrityError`` to the bot.
    The fix is an ``INSERT ... ON CONFLICT DO NOTHING`` so at most one
    request creates the row and the loser falls through to a fresh
    ``SELECT``. The username/display_name refresh stays in a separate
    statement because we don't want to clobber a non-empty display name
    with an empty Telegram ``first_name``.
    """
    stmt = (
        pg_insert(User)
        .values(
            tg_user_id=tg_user_id,
            username=username,
            display_name=first_name or "",
        )
        .on_conflict_do_nothing(index_elements=[User.tg_user_id])
    )
    await session.execute(stmt)
    await session.commit()

    user = (await session.execute(select(User).where(User.tg_user_id == tg_user_id))).scalar_one()

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
    return user


# ── Stats ─────────────────────────────────────────────────────────────────


async def _deals_stats(session: AsyncSession, user_id: int) -> dict[str, Any]:
    """Aggregate counts + per-currency completed volume for a user.

    Counts every deal the user participates in (buyer OR seller).

    M-5 — after the multi-currency rewrite ``Deal.amount`` is
    denominated in ``Deal.currency_id``. Summing it across mixed
    currencies (e.g. USDT + TON + BTC) produces a single number with
    no real meaning. ``by_currency`` is the per-currency breakdown
    used by the bot text renderer; counts stay aggregate because
    "how many deals did the user finish" is currency-neutral.

    L-2 — the legacy USD-only ``Deal.sum`` column is gone and
    ``currency_id`` is NOT NULL on every row, so the previously
    needed "legacy bucket" fallback (``currency_id IS NULL`` rows
    aggregated under a synthetic ``USD`` code) is no longer
    reachable.
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

    sales_count = (
        await session.execute(
            select(func.count(Deal.id)).where(
                Deal.seller_id == user_id, Deal.status == DealStatus.completed
            )
        )
    ).scalar_one()

    # Audit M3 — ``pending_payment`` is reserved in ``DealStatus`` but
    # no transition writes it; counting it alongside
    # ``pending_confirmation`` was always zero on top of the
    # confirmation count and confused readers.
    pending_payment_count = (
        await session.execute(
            select(func.count(Deal.id)).where(
                or_(Deal.buyer_id == user_id, Deal.seller_id == user_id),
                Deal.status == DealStatus.pending_confirmation,
            )
        )
    ).scalar_one()

    # Per-currency completed volume. Buys + sales tracked separately
    # because the profile card surfaces them on different lines.
    by_currency: dict[str, dict[str, float | int]] = {}

    currencies = (await session.execute(select(Currency))).scalars().all()
    by_id = {c.id: c for c in currencies}

    buys_rows = (
        await session.execute(
            select(Deal.currency_id, func.coalesce(func.sum(Deal.amount), 0))
            .where(
                Deal.buyer_id == user_id,
                Deal.status == DealStatus.completed,
            )
            .group_by(Deal.currency_id)
        )
    ).all()
    sales_rows = (
        await session.execute(
            select(Deal.currency_id, func.coalesce(func.sum(Deal.amount), 0))
            .where(
                Deal.seller_id == user_id,
                Deal.status == DealStatus.completed,
            )
            .group_by(Deal.currency_id)
        )
    ).all()

    def _bucket(code: str, decimals: int) -> dict[str, float | int]:
        return by_currency.setdefault(
            code, {"code": code, "decimals": decimals, "buys_sum": 0.0, "sales_sum": 0.0}
        )

    for currency_id, amount in buys_rows:
        cur = by_id.get(currency_id)
        if cur is None:
            continue
        b = _bucket(cur.code, cur.decimals)
        b["buys_sum"] = float(b["buys_sum"]) + float(amount or 0)

    for currency_id, amount in sales_rows:
        cur = by_id.get(currency_id)
        if cur is None:
            continue
        b = _bucket(cur.code, cur.decimals)
        b["sales_sum"] = float(b["sales_sum"]) + float(amount or 0)

    # Stable sort: largest combined-volume first, then code asc, so the
    # most relevant currency shows at the top regardless of insertion order.
    by_currency_list = sorted(
        by_currency.values(),
        key=lambda b: (-(float(b["buys_sum"]) + float(b["sales_sum"])), str(b["code"])),
    )

    return {
        "total_count": int(total_count),
        "buys_count": int(buys_count),
        "sales_count": int(sales_count),
        "pending_payment_count": int(pending_payment_count),
        "by_currency": by_currency_list,
        # Banner thumbnail is currency-neutral: shows the count of
        # completed deals so the headline number can't lie when the
        # user trades across multiple assets. Text body carries the
        # per-currency breakdown.
        "completed_count": int(buys_count) + int(sales_count),
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
        by_currency=stats["by_currency"],
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
            total_volume=float(stats["completed_count"]),
            deal_count=stats["total_count"],
            sale_count=stats["sales_count"],
        ),
        filename="deals.jpg",
    )
    await _send(message, body, keyboard=kb, photo=photo)


async def _fetch_avatar_png(message: Message, tg_user_id: int) -> bytes | None:
    """Download the Telegram profile photo as bytes, or ``None`` if the
    user has no avatar / the call fails.

    Failures here are non-fatal — the renderer falls back to a
    placeholder. Telegram caches ``file_id`` server-side, so this is
    cheap on the second hit.
    """
    bot = message.bot
    if bot is None:
        return None
    try:
        photos = await bot.get_user_profile_photos(user_id=tg_user_id, limit=1)
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_user_profile_photos failed for %s: %s", tg_user_id, exc)
        return None
    if not photos.photos or not photos.photos[0]:
        return None
    # Pick the largest size (the last entry in the per-row list is the
    # original-resolution variant).
    size = photos.photos[0][-1]
    try:
        buf = await bot.download(size.file_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("avatar download failed for %s: %s", tg_user_id, exc)
        return None
    if buf is None:
        return None
    data = buf.read() if hasattr(buf, "read") else bytes(buf)
    return data or None


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
        sales_count=stats["sales_count"],
        by_currency=stats["by_currency"],
    )
    avatar_png = await _fetch_avatar_png(message, tg_user_id)
    photo = BufferedInputFile(
        banners.render_profile(
            username=user.username,
            deposit=float(user.trust_deposit_balance or 0),
            avatar_png=avatar_png,
        ),
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
    return user


async def toggle_anonymous(tg_user_id: int) -> User:
    async with async_session() as session:
        user = await _load_user(session, tg_user_id)
        user.is_anonymous_deals = not user.is_anonymous_deals
        await session.commit()
        return user


async def toggle_hidden(tg_user_id: int) -> User:
    async with async_session() as session:
        user = await _load_user(session, tg_user_id)
        user.is_hidden_profile = not user.is_hidden_profile
        await session.commit()
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
        sales_count=stats["sales_count"],
        by_currency=stats["by_currency"],
    )
    return body, keyboards.profile_keyboard()
