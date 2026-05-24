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
from backend.app.config import settings
from backend.app.db import async_session
from backend.app.models import Currency, Deal, DealStatus, User

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
    currency_code: str | None = "USDT",
    amount: float | None = None,
) -> Deal:
    """Insert a Deal, optionally pinned to a specific currency.

    Post-M-5, ``Deal.amount`` + ``Deal.currency_id`` are what the bot
    stats query reads. Tests that want to exercise the per-currency
    branch pass ``amount`` + ``currency_code``; ``currency_code`` is
    required because ``currency_id`` is NOT NULL after L-2.
    """
    async with async_session() as session:
        assert currency_code, "currency_code is required after L-2 — Deal.currency_id is NOT NULL"
        cur = (
            await session.execute(select(Currency).where(Currency.code == currency_code))
        ).scalar_one()
        currency_id = cur.id
        d = Deal(
            buyer_id=buyer_id,
            seller_id=seller_id,
            status=status,
            currency_id=currency_id,
            amount=amount if amount is not None else sum_,
        )
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


def test_button_text_variants_cover_vs16_and_bare_keyword():
    """Reply-keyboard taps must route regardless of how the client renders
    the leading emoji — with U+FE0F, without it, or with the emoji
    omitted entirely. ``SEARCH_BUTTON_TEXTS`` and friends are what the
    handler filters use, so a missed variant here is a silent dead
    button on real Telegram clients."""
    assert keyboards.SEARCH_BUTTON in keyboards.SEARCH_BUTTON_TEXTS
    assert "Поиск" in keyboards.SEARCH_BUTTON_TEXTS
    # Gear is a U+2699 BMP codepoint — both with and without VS16
    # (U+FE0F) presentation must route to the help handler.
    assert "⚙ Помощь" in keyboards.HELP_BUTTON_TEXTS
    assert "⚙\ufe0f Помощь" in keyboards.HELP_BUTTON_TEXTS
    assert "Помощь" in keyboards.HELP_BUTTON_TEXTS
    # SMP emojis (📁, 👤, 🔎) are usually presentation-stable but we
    # still tolerate stripped VS16 to be safe.
    assert "📁 Сделки" in keyboards.DEALS_BUTTON_TEXTS
    assert "Сделки" in keyboards.DEALS_BUTTON_TEXTS
    assert "👤 Профиль" in keyboards.PROFILE_BUTTON_TEXTS
    assert "Профиль" in keyboards.PROFILE_BUTTON_TEXTS
    # Every variant set must be disjoint — a "Поиск" tap should never
    # route to the deals handler and vice versa.
    sets = [
        keyboards.SEARCH_BUTTON_TEXTS,
        keyboards.DEALS_BUTTON_TEXTS,
        keyboards.PROFILE_BUTTON_TEXTS,
        keyboards.HELP_BUTTON_TEXTS,
    ]
    for i, a in enumerate(sets):
        for b in sets[i + 1 :]:
            assert a.isdisjoint(b), f"button variants overlap: {a & b}"


def test_search_keyboard_has_two_webapp_buttons(monkeypatch: pytest.MonkeyPatch):
    # Telegram only accepts inline ``web_app=`` buttons whose URL is
    # HTTPS; pin the setting so this test exercises the proper Mini
    # App launch path rather than the http fallback covered below.
    monkeypatch.setattr(settings, "webapp_url", "https://example.com/app")
    kb = keyboards.search_keyboard()
    flat = [b for row in kb.inline_keyboard for b in row]
    assert len(flat) == 2
    assert all(b.web_app is not None for b in flat)
    assert all(b.url is None for b in flat)


@pytest.mark.parametrize(
    "webapp_url",
    [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://10.0.0.1:5173",
        "http://example.com",
        "",
    ],
)
def test_search_keyboard_falls_back_to_callback_when_webapp_not_https(
    monkeypatch: pytest.MonkeyPatch, webapp_url: str
):
    """Reproduces the dropped-button bug — final form.

    Telegram rejects ``sendMessage`` / ``sendPhoto`` calls whose inline
    keyboard contains *either*:

    * a ``web_app=`` button with a non-HTTPS URL
      (``Bad Request: BUTTON_TYPE_INVALID``); **or**
    * a plain ``url=`` button that points at ``localhost`` /
      private-IP / ``http://`` (``Bad Request: ... is invalid: Wrong
      HTTP URL``).

    Pre-fix every section handler hit one of these with the default
    ``WEBAPP_URL=http://localhost:5173`` and the user saw the bot
    silently ignore their tap. PR #168 swapped ``web_app=`` for
    ``url=`` which moved the same silent failure under a different
    Telegram error class — confirmed in a live test against
    ``@EWGarant_bot``. We now fall back all the way to
    ``callback_data=``: it has no Telegram-side URL validation, so the
    keyboard always renders and tapping the button surfaces a single,
    actionable diagnostic alert via ``cb_tma_unavailable`` in
    ``handlers.py`` instead of nothing.
    """
    monkeypatch.setattr(settings, "webapp_url", webapp_url)
    kb = keyboards.search_keyboard()
    flat = [b for row in kb.inline_keyboard for b in row]
    assert len(flat) == 2
    assert all(b.web_app is None for b in flat)
    assert all(b.url is None for b in flat)
    assert all(
        b.callback_data is not None
        and b.callback_data.startswith(keyboards.CB_TMA_UNAVAILABLE_PREFIX)
        for b in flat
    )
    # Each Mini App button must carry its original path in the callback
    # data so the diagnostic handler can tell the operator *which*
    # section the user wanted to open.
    suffixes = sorted(
        b.callback_data.removeprefix(keyboards.CB_TMA_UNAVAILABLE_PREFIX) for b in flat
    )
    assert suffixes == ["/search", "/search/categories"]
    # And nothing must exceed Telegram's 64-byte callback_data cap.
    assert all(len(b.callback_data.encode("utf-8")) <= 64 for b in flat)


def test_help_keyboard_surfaces_in_app_faq_button(
    monkeypatch: pytest.MonkeyPatch,
):
    # V14 — the help keyboard always shows a Mini App FAQ button as
    # its first row; external admin / community chat links were
    # removed. The remaining optional URL rows (docs / arbitration)
    # depend on operator-supplied env vars which are empty in tests.
    monkeypatch.setattr(settings, "webapp_url", "https://example.com/app")
    kb = keyboards.help_keyboard()
    flat = [b for row in kb.inline_keyboard for b in row]
    assert len(flat) == 1
    assert flat[0].web_app is not None
    assert flat[0].web_app.url.endswith("/support")


def test_webapp_url_is_https_detects_protocol(monkeypatch: pytest.MonkeyPatch):
    """The helper that drives the fallback must treat any non-HTTPS
    URL (http, scheme-less, empty) as 'not safe for web_app'."""
    monkeypatch.setattr(settings, "webapp_url", "https://example.com/app")
    assert keyboards.webapp_url_is_https() is True
    monkeypatch.setattr(settings, "webapp_url", "HTTPS://example.com/app")
    assert keyboards.webapp_url_is_https() is True
    monkeypatch.setattr(settings, "webapp_url", "http://localhost:5173")
    assert keyboards.webapp_url_is_https() is False
    monkeypatch.setattr(settings, "webapp_url", "")
    assert keyboards.webapp_url_is_https() is False


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
        by_currency=[
            {"code": "USDT", "decimals": 2, "buys_sum": 20.5, "sales_sum": 22.0},
            {"code": "TON", "decimals": 4, "buys_sum": 0.0, "sales_sum": 5.25},
        ],
        total_count=4,
        buys_count=2,
        sales_count=2,
        pending_payment_count=1,
    )
    assert "Сумма сделок" in body
    # USDT line: 20.5 + 22.0 = 42.5 with 2 decimals, trailing zero stripped
    assert "42.5 USDT" in body
    # TON line: 0.0 + 5.25 with 4 decimals (trailing zeros stripped)
    assert "5.25 TON" in body
    assert "Покупок: <b>2</b>" in body
    assert "Продаж: <b>2</b>" in body
    assert "Ожидающие оплаты: <b>1</b>" in body


def test_deals_summary_with_no_completed_deals_shows_dash():
    body = texts.deals_summary(
        by_currency=[],
        total_count=0,
        buys_count=0,
        sales_count=0,
        pending_payment_count=0,
    )
    assert "Сумма сделок: <b>—</b>" in body


def test_profile_summary_text_uses_username_and_status():
    user = SimpleNamespace(
        tg_user_id=99,
        username="bob",
        display_name="Bob",
        is_admin=False,
        is_arbiter=True,
        good=4,
        bad=1,
        trust_deposit_balance=12.0,
    )
    body = texts.profile_summary(
        user,
        buys_count=3,
        sales_count=2,
        by_currency=[
            {"code": "USDT", "decimals": 2, "buys_sum": 300.0, "sales_sum": 200.0},
        ],
    )
    assert "@bob" in body
    assert "Арбитр" in body
    assert "4.0/5.0 (5)" in body
    assert "$12" in body
    assert "Покупок:</b> 3" in body
    assert "300 USDT" in body
    assert "200 USDT" in body


def test_profile_summary_with_multi_currency():
    """Multi-currency users see one ``amount CODE`` entry per currency
    that has non-zero buys / sales; empty buckets are hidden."""
    user = SimpleNamespace(
        tg_user_id=99,
        username="alice",
        display_name="Alice",
        is_admin=False,
        is_arbiter=False,
        good=0,
        bad=0,
        trust_deposit_balance=0.0,
    )
    body = texts.profile_summary(
        user,
        buys_count=2,
        sales_count=1,
        by_currency=[
            {"code": "USDT", "decimals": 2, "buys_sum": 125.5, "sales_sum": 0.0},
            {"code": "TON", "decimals": 4, "buys_sum": 0.0, "sales_sum": 3.0},
        ],
    )
    # Buys line shows only USDT (TON buys is 0), sales line shows only TON.
    assert "Покупок:</b> 2 шт, на сумму: 125.5 USDT" in body
    assert "Продаж:</b> 1 шт, на сумму: 3 TON" in body


def test_profile_summary_escapes_username_for_html_parse_mode():
    """``bot.notify`` sends DMs with ``parse_mode=HTML``; usernames must
    therefore be HTML-escaped at the render layer, matching how
    ``display_name`` is treated.

    Telegram's own username charset cannot in practice carry ``<`` /
    ``>`` / ``&``, but a future code path that bypasses the upstream
    constraint (e.g. CSV import, admin override, schema relaxation)
    must not be able to smuggle markup into a bot DM. The regression
    asserts no raw ``<`` survives in the rendered body.
    """
    user = SimpleNamespace(
        tg_user_id=42,
        username="<b>evil</b>&",
        display_name="<script>alert(1)</script>",
        is_admin=False,
        is_arbiter=False,
        good=0,
        bad=0,
        trust_deposit_balance=0.0,
    )
    body = texts.profile_summary(
        user,
        buys_count=0,
        sales_count=0,
        by_currency=[],
    )
    # Raw username / display_name markup must not appear unescaped in
    # the rendered body — both fields are now consistently escaped.
    assert "<b>evil</b>" not in body
    assert "<script>" not in body
    # The escaped form should be present instead.
    assert "&lt;b&gt;evil&lt;/b&gt;&amp;" in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


def test_settings_summary_escapes_username_for_html_parse_mode():
    """Same defence-in-depth contract as ``profile_summary`` — the
    settings card also interpolates ``user.username`` into an HTML
    parse-mode body.
    """
    user = SimpleNamespace(username="<img src=x onerror=alert(1)>")
    body = texts.settings_summary(user)
    assert "<img" not in body
    assert "&lt;img src=x onerror=alert(1)&gt;" in body


# ── DB-backed stats ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deals_stats_counts_buys_sales_and_pending():
    alice = await _seed_user(5001, username="alice")
    bob = await _seed_user(5002, username="bob")

    # Two completed deals where alice buys from bob, one completed
    # one where alice sells to bob, and one pending_payment one where
    # alice is also a participant.
    await _seed_deal(buyer_id=alice.id, seller_id=bob.id, currency_code="USDT", amount=50.0)
    await _seed_deal(buyer_id=alice.id, seller_id=bob.id, currency_code="USDT", amount=75.0)
    await _seed_deal(buyer_id=bob.id, seller_id=alice.id, currency_code="USDT", amount=200.0)
    await _seed_deal(
        buyer_id=alice.id,
        seller_id=bob.id,
        currency_code="USDT",
        amount=10.0,
        status=DealStatus.pending_confirmation,
    )

    async with async_session() as session:
        stats = await sections._deals_stats(session, alice.id)

    assert stats["buys_count"] == 2
    assert stats["sales_count"] == 1
    assert stats["pending_payment_count"] == 1
    assert stats["total_count"] == 4
    # All deals are USDT in this test, so the single bucket carries both
    # buys + sales.
    by = stats["by_currency"]
    assert len(by) == 1
    assert by[0]["code"] == "USDT"
    assert by[0]["buys_sum"] == 125.0
    assert by[0]["sales_sum"] == 200.0


@pytest.mark.asyncio
async def test_deals_stats_groups_volume_by_currency():
    """M-5 — completed deals across multiple currencies must show up as
    distinct buckets in ``by_currency`` and never be summed across them."""
    alice = await _seed_user(6001, username="alice_mc")
    bob = await _seed_user(6002, username="bob_mc")

    # 100 USDT buy + 200 USDT sale + 5 TON buy + 1.5 TON sale.
    await _seed_deal(buyer_id=alice.id, seller_id=bob.id, currency_code="USDT", amount=100.0)
    await _seed_deal(buyer_id=bob.id, seller_id=alice.id, currency_code="USDT", amount=200.0)
    await _seed_deal(buyer_id=alice.id, seller_id=bob.id, currency_code="TON", amount=5.0)
    await _seed_deal(buyer_id=bob.id, seller_id=alice.id, currency_code="TON", amount=1.5)

    async with async_session() as session:
        stats = await sections._deals_stats(session, alice.id)

    assert stats["buys_count"] == 2
    assert stats["sales_count"] == 2
    by = {b["code"]: b for b in stats["by_currency"]}
    assert {"USDT", "TON"} <= set(by)
    assert by["USDT"]["buys_sum"] == 100.0
    assert by["USDT"]["sales_sum"] == 200.0
    assert by["TON"]["buys_sum"] == 5.0
    assert by["TON"]["sales_sum"] == 1.5
    # Sort order: USDT (combined 300) before TON (combined 6.5).
    codes_in_order = [b["code"] for b in stats["by_currency"]]
    assert codes_in_order.index("USDT") < codes_in_order.index("TON")


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


# ── HTTP-WEBAPP fallback diagnostic callback ─────────────────────────────


@pytest.mark.asyncio
async def test_cb_tma_unavailable_pops_up_alert_when_tapped():
    """When WEBAPP_URL is not HTTPS, ``_webapp_button`` emits a
    ``callback_data=bot:tma_unavail:<path>`` button instead of a
    ``web_app=`` / ``url=`` one. Tapping that button must call
    ``callback.answer(..., show_alert=True)`` with an actionable text,
    so the section message no longer looks dead and the operator gets
    a single, copy-pasteable diagnostic explaining what to fix.
    """
    cb = _fake_callback(5100)
    cb.data = keyboards.CB_TMA_UNAVAILABLE_PREFIX + "/search"

    await handlers.cb_tma_unavailable(cb)

    cb.answer.assert_awaited_once()
    call = cb.answer.call_args
    assert call.kwargs.get("show_alert") is True
    text = (call.args[0] if call.args else "") or call.kwargs.get("text", "")
    assert "WEBAPP_URL" in text
    assert "HTTPS" in text
