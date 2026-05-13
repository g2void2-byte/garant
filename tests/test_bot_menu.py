"""Bot menu (P3.2) coverage.

Aiogram is run "headless" — we don't spin up a real polling loop. Instead we
build minimal stand-ins for ``Message`` / ``CallbackQuery`` with AsyncMocks
on the answer methods and call the handler functions directly. That keeps
the suite fast and avoids any network egress.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.app.bot import handlers, keyboards, sections, texts
from backend.app.db import async_session
from backend.app.models import Deal, DealStatus, User

# ── Helpers ──────────────────────────────────────────────────────────────


def _fake_message(tg_user_id: int = 5001, username: str = "alice", first_name: str = "Alice"):
    """Build a SimpleNamespace that quacks like aiogram's ``Message``."""
    return SimpleNamespace(
        from_user=SimpleNamespace(id=tg_user_id, username=username, first_name=first_name),
        answer=AsyncMock(),
        answer_photo=AsyncMock(),
    )


def _fake_callback(tg_user_id: int, *, photo: bool = False):
    """Build a SimpleNamespace that quacks like aiogram's ``CallbackQuery``."""
    inner = SimpleNamespace(
        photo=([SimpleNamespace()] if photo else None),
        edit_text=AsyncMock(),
        edit_caption=AsyncMock(),
    )
    return SimpleNamespace(
        from_user=SimpleNamespace(id=tg_user_id, username="alice", first_name="Alice"),
        message=inner,
        answer=AsyncMock(),
        data=None,
    )


async def _seed_user(tg_user_id: int = 5001, *, username: str = "alice") -> User:
    async with async_session() as session:
        user = User(tg_user_id=tg_user_id, username=username, display_name=username.capitalize())
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _seed_deal(
    *,
    buyer_id: int,
    seller_id: int,
    sum_: float = 100.0,
    status: DealStatus = DealStatus.completed,
) -> Deal:
    async with async_session() as session:
        d = Deal(buyer_id=buyer_id, seller_id=seller_id, sum=sum_, status=status)
        session.add(d)
        await session.commit()
        await session.refresh(d)
        return d


# ── Static rendering ─────────────────────────────────────────────────────


def test_main_reply_keyboard_has_four_buttons():
    kb = keyboards.main_reply_keyboard()
    flat = [b.text for row in kb.keyboard for b in row]
    assert flat == [
        keyboards.SEARCH_BUTTON,
        keyboards.DEALS_BUTTON,
        keyboards.PROFILE_BUTTON,
        keyboards.HELP_BUTTON,
    ]
    assert kb.resize_keyboard is True


def test_search_keyboard_has_two_webapp_buttons():
    kb = keyboards.search_keyboard()
    flat = [b for row in kb.inline_keyboard for b in row]
    assert len(flat) == 2
    assert all(b.web_app is not None for b in flat)


def test_help_keyboard_falls_back_to_open_app_when_unconfigured():
    # In tests no BOT_* URL env vars are set — config defaults are empty,
    # so the keyboard should still surface at least one usable button.
    kb = keyboards.help_keyboard()
    flat = [b for row in kb.inline_keyboard for b in row]
    assert len(flat) == 1
    assert flat[0].web_app is not None


def test_settings_keyboard_marks_active_toggles():
    user_off = SimpleNamespace(is_anonymous_deals=False, is_hidden_profile=False)
    user_on = SimpleNamespace(is_anonymous_deals=True, is_hidden_profile=True)

    kb_off = keyboards.settings_keyboard(user_off)
    kb_on = keyboards.settings_keyboard(user_on)

    texts_off = [b.text for row in kb_off.inline_keyboard for b in row]
    texts_on = [b.text for row in kb_on.inline_keyboard for b in row]

    assert any(t.startswith("❌ Анонимность") for t in texts_off)
    assert any(t.startswith("❌ Скрытый профиль") for t in texts_off)
    assert any(t.startswith("✅ Анонимность") for t in texts_on)
    assert any(t.startswith("✅ Скрытый профиль") for t in texts_on)


def test_deals_summary_text_contains_all_metrics():
    body = texts.deals_summary(
        total_volume=42.5,
        total_count=4,
        buys_count=2,
        sales_count=2,
        pending_payment_count=1,
    )
    assert "Сумма сделок" in body
    assert "$42.5" in body
    assert "Покупок: <b>2</b>" in body
    assert "Продаж: <b>2</b>" in body
    assert "Ожидающие оплаты: <b>1</b>" in body


def test_profile_summary_text_uses_username_and_status():
    user = SimpleNamespace(
        tg_user_id=99,
        username="bob",
        display_name="Bob",
        is_admin=False,
        is_moderator=False,
        is_arbiter=True,
        good=4,
        bad=1,
        frozen_balance=12.0,
    )
    body = texts.profile_summary(
        user,
        buys_count=3,
        buys_sum=300.0,
        sales_count=2,
        sales_sum=200.0,
    )
    assert "@bob" in body
    assert "Арбитр" in body
    assert "4.0/5.0 (5)" in body
    assert "$12" in body
    assert "Покупок:</b> 3" in body


# ── DB-backed stats ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deals_stats_counts_buys_sales_and_pending():
    alice = await _seed_user(5001, username="alice")
    bob = await _seed_user(5002, username="bob")

    # Two completed deals where alice buys from bob, one in-progress one
    # where alice sells to bob, and one pending_payment one where bob is
    # the buyer (so it should not count toward alice's pending bucket).
    await _seed_deal(buyer_id=alice.id, seller_id=bob.id, sum_=50, status=DealStatus.completed)
    await _seed_deal(buyer_id=alice.id, seller_id=bob.id, sum_=75, status=DealStatus.completed)
    await _seed_deal(buyer_id=bob.id, seller_id=alice.id, sum_=200, status=DealStatus.completed)
    await _seed_deal(
        buyer_id=alice.id, seller_id=bob.id, sum_=10, status=DealStatus.pending_confirmation
    )

    async with async_session() as session:
        stats = await sections._deals_stats(session, alice.id)

    assert stats["buys_count"] == 2
    assert stats["sales_count"] == 1
    assert stats["buys_sum"] == 125.0
    assert stats["sales_sum"] == 200.0
    assert stats["pending_payment_count"] == 1
    assert stats["total_count"] == 4
    assert stats["total_volume"] == 325.0


# ── Handler dispatch ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_search_sends_text_and_search_keyboard():
    msg = _fake_message()
    await handlers.on_search(msg)
    # Banner files ship with the repo so the handler always uses ``answer_photo``.
    msg.answer_photo.assert_awaited_once()
    kwargs = msg.answer_photo.call_args.kwargs
    assert "Поиск" in kwargs["caption"]
    kb = kwargs["reply_markup"]
    assert kb is not None
    flat = [b for row in kb.inline_keyboard for b in row]
    assert len(flat) == 2


@pytest.mark.asyncio
async def test_on_deals_creates_user_and_sends_stats():
    msg = _fake_message(tg_user_id=5050, username="newbie", first_name="Newbie")
    await handlers.on_deals(msg)
    msg.answer_photo.assert_awaited_once()
    body = msg.answer_photo.call_args.kwargs["caption"]
    # Fresh user has no deals — every bucket must be zero.
    assert "Покупок: <b>0</b>" in body
    assert "Продаж: <b>0</b>" in body
    assert "Ожидающие оплаты: <b>0</b>" in body

    async with async_session() as session:
        user = (await session.execute(select(User).where(User.tg_user_id == 5050))).scalar_one()
    assert user.username == "newbie"


@pytest.mark.asyncio
async def test_on_profile_renders_profile_card():
    msg = _fake_message(tg_user_id=5060, username="cara", first_name="Cara")
    await handlers.on_profile(msg)
    msg.answer_photo.assert_awaited_once()
    kwargs = msg.answer_photo.call_args.kwargs
    assert "@cara" in kwargs["caption"]
    # Inline keyboard must always include the settings callback button.
    kb = kwargs["reply_markup"]
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]
    assert keyboards.CB_SETTINGS in callbacks


@pytest.mark.asyncio
async def test_on_help_sends_help_caption():
    msg = _fake_message()
    await handlers.on_help(msg)
    msg.answer_photo.assert_awaited_once()
    assert "Помощь" in msg.answer_photo.call_args.kwargs["caption"]


# ── Callback toggles ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cb_toggle_anon_flips_field_and_redraws_text():
    await _seed_user(5070, username="dora")
    cb = _fake_callback(5070)

    await handlers.cb_toggle_anon(cb)

    cb.message.edit_text.assert_awaited_once()
    call_kwargs = cb.message.edit_text.call_args.kwargs
    # Updated keyboard should now show ✅ on the anon row.
    kb = call_kwargs["reply_markup"]
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert any(t.startswith("✅ Анонимность") for t in labels)
    assert any(t.startswith("❌ Скрытый профиль") for t in labels)

    async with async_session() as session:
        u = (await session.execute(select(User).where(User.tg_user_id == 5070))).scalar_one()
    assert u.is_anonymous_deals is True
    assert u.is_hidden_profile is False
    cb.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_cb_toggle_hidden_flips_field():
    await _seed_user(5071, username="erin")
    cb = _fake_callback(5071)

    await handlers.cb_toggle_hidden(cb)

    async with async_session() as session:
        u = (await session.execute(select(User).where(User.tg_user_id == 5071))).scalar_one()
    assert u.is_hidden_profile is True

    # Toggle again — should flip back to False.
    await handlers.cb_toggle_hidden(_fake_callback(5071))
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.tg_user_id == 5071))).scalar_one()
    assert u.is_hidden_profile is False


@pytest.mark.asyncio
async def test_cb_settings_opens_settings_card_and_back_returns_to_profile():
    await _seed_user(5080, username="fran")

    open_cb = _fake_callback(5080)
    await handlers.cb_settings(open_cb)
    open_cb.message.edit_text.assert_awaited_once()
    settings_args = open_cb.message.edit_text.call_args
    settings_text = settings_args.args[0]
    assert "Настройки профиля" in settings_text

    back_cb = _fake_callback(5080)
    await handlers.cb_back_to_profile(back_cb)
    back_cb.message.edit_text.assert_awaited_once()
    profile_text = back_cb.message.edit_text.call_args.args[0]
    assert "@fran" in profile_text


@pytest.mark.asyncio
async def test_callbacks_use_edit_caption_when_message_has_photo():
    await _seed_user(5090, username="gary")
    cb = _fake_callback(5090, photo=True)

    await handlers.cb_settings(cb)

    cb.message.edit_caption.assert_awaited_once()
    cb.message.edit_text.assert_not_awaited()
