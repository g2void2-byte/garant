"""Regression tests for the Medium-severity follow-ups from the May
review report.

* **M1** — maintenance flag is cached in-process; admin toggle drops
  the cache so changes take effect immediately on that worker.
* **M3** — ``auth_date`` in initData must be within ``[now-86400,
  now+300]``; pre-fix only the past bound was checked.
* **M5** — money paths in ``services_wallet`` / ``services_deals``
  persist ``Decimal`` instead of round-tripping through ``float``.
  Pre-fix a ``USDT`` deposit at the 10^10 scale would lose
  sub-satoshi precision on every read-modify-write.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from sqlalchemy import select

from backend.app import maintenance as maintenance_module
from backend.app.config import settings as app_settings
from backend.app.db import async_session
from backend.app.models import AppSettings, Currency, User, UserBalance
from backend.app.security import InitDataError, verify_init_data
from backend.app.services_deals import _debit, _refund, _release_to
from backend.app.services_wallet import get_or_create_balance

from .helpers import TOTP_BYPASS_CODE, auth_headers, signed_init_data

# --- M1: maintenance cache --------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_maintenance_cache():
    """Each test starts with an empty cache so we observe a fresh DB load."""
    maintenance_module.invalidate_cache()
    yield
    maintenance_module.invalidate_cache()


@pytest.mark.asyncio
async def test_maintenance_cache_serves_subsequent_lookups_without_db():
    """The first call populates the cache; the second uses it.

    We swap the underlying ``_load_from_db`` for a counter, prime
    the cache, then call ``_get_maintenance`` repeatedly and assert
    the loader fires only once.
    """
    calls = 0
    real_load = maintenance_module._load_from_db

    async def _counting_load():
        nonlocal calls
        calls += 1
        return False, ""

    maintenance_module._load_from_db = _counting_load
    try:
        await maintenance_module._get_maintenance()
        await maintenance_module._get_maintenance()
        await maintenance_module._get_maintenance()
    finally:
        maintenance_module._load_from_db = real_load
    assert calls == 1, calls


@pytest.mark.asyncio
async def test_maintenance_invalidate_cache_forces_refresh():
    """Admin toggle hooks into ``invalidate_cache``; the next request
    must re-hit the DB instead of serving stale data.
    """
    calls = 0
    real_load = maintenance_module._load_from_db

    async def _counting_load():
        nonlocal calls
        calls += 1
        return False, ""

    maintenance_module._load_from_db = _counting_load
    try:
        await maintenance_module._get_maintenance()
        maintenance_module.invalidate_cache()
        await maintenance_module._get_maintenance()
    finally:
        maintenance_module._load_from_db = real_load
    assert calls == 2, calls


@pytest.mark.asyncio
async def test_admin_settings_patch_invalidates_maintenance_cache(client):
    """End-to-end: PATCH /api/admin/settings with a new maintenance
    value drops the cache and the next probe reflects the new state.
    """
    # Build an admin user. We bypass the PIN/2FA dance by using the
    # TOTP_BYPASS header.
    admin_tg = 5101
    init = signed_init_data(admin_tg, "m1_admin")
    headers = auth_headers(init)
    # Force-create the user via /api/me then promote to admin in DB.
    await client.get("/api/me", headers=headers)
    async with async_session() as session:
        user = (await session.execute(select(User).where(User.tg_user_id == admin_tg))).scalar_one()
        user.is_admin = True
        await session.commit()

    # Prime the cache to a known state (disabled).
    async with async_session() as session:
        row = (
            await session.execute(select(AppSettings).order_by(AppSettings.id).limit(1))
        ).scalar_one_or_none()
        if row is None:
            row = AppSettings()
            session.add(row)
        row.maintenance_enabled = False
        row.maintenance_message = ""
        await session.commit()
    maintenance_module.invalidate_cache()
    enabled, _ = await maintenance_module._get_maintenance()
    assert enabled is False

    # PATCH the settings via the admin endpoint.
    resp = await client.patch(
        "/api/admin/settings",
        headers={**headers, "X-Totp-Code": TOTP_BYPASS_CODE},
        json={"maintenance_enabled": True, "maintenance_message": "test-m1"},
    )
    assert resp.status_code == 200, resp.text

    # Without invalidation, the cache would have served a stale
    # "False" here. With the hook, we see the new state immediately.
    enabled, message = await maintenance_module._get_maintenance()
    assert enabled is True
    assert message == "test-m1"


# --- M3: auth_date upper bound ---------------------------------------------


def _signed_init_data_with_auth_date(tg_user_id: int, auth_date: int, username: str) -> str:
    """Like ``signed_init_data`` but pins ``auth_date`` explicitly so
    we can construct a token that's *in the future*.
    """
    user = json.dumps(
        {"id": tg_user_id, "first_name": username, "username": username},
        separators=(",", ":"),
    )
    items = sorted([("auth_date", str(auth_date)), ("user", user)])
    data_check_string = "\n".join(f"{k}={v}" for k, v in items)
    secret_key = hmac.new(b"WebAppData", app_settings.bot_token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({"user": user, "auth_date": str(auth_date), "hash": h})


def test_auth_date_in_far_future_is_rejected():
    """``auth_date`` more than 5 min in the future is rejected even
    when the HMAC matches.
    """
    # Skip when the test config disables HMAC entirely.
    if app_settings.allow_unsigned_init_data:
        pytest.skip("HMAC bypassed in this test config; M3 path not reachable")
    future_auth = int(time.time()) + 3600  # 1h in the future
    init = _signed_init_data_with_auth_date(9101, future_auth, "future9101")
    with pytest.raises(InitDataError) as exc:
        verify_init_data(init)
    assert "future" in str(exc.value).lower()


def test_auth_date_within_drift_window_is_accepted():
    """A small forward drift (≤ 5 min) is still accepted so NTP
    wobble doesn't lock real users out.
    """
    if app_settings.allow_unsigned_init_data:
        pytest.skip("HMAC bypassed in this test config")
    near_future = int(time.time()) + 60  # 1 min in the future
    init = _signed_init_data_with_auth_date(9102, near_future, "drift9102")
    parsed = verify_init_data(init)
    assert parsed["id"] == 9102


def test_auth_date_in_past_still_expires():
    """The old upper bound (24h in the past) is unchanged."""
    if app_settings.allow_unsigned_init_data:
        pytest.skip("HMAC bypassed in this test config")
    stale_auth = int(time.time()) - 90000  # 25h in the past
    init = _signed_init_data_with_auth_date(9103, stale_auth, "stale9103")
    with pytest.raises(InitDataError) as exc:
        verify_init_data(init)
    assert "expired" in str(exc.value).lower()


# --- V5-A-1: shortened replay window (15 min default) ----------------------


def test_auth_date_just_past_new_window_is_rejected():
    """An init-data 16 minutes old must be rejected under the new
    15-minute default replay window. Pre-V5-A-1 it would have been
    accepted (the bound was 24h).
    """
    if app_settings.allow_unsigned_init_data:
        pytest.skip("HMAC bypassed in this test config")
    just_past = int(time.time()) - 16 * 60  # 16 min in the past
    init = _signed_init_data_with_auth_date(9104, just_past, "just_past9104")
    with pytest.raises(InitDataError) as exc:
        verify_init_data(init)
    assert "expired" in str(exc.value).lower()


def test_auth_date_within_new_window_is_accepted():
    """An init-data 14 minutes old is still inside the 15-min window
    and must be accepted; this guards against the window being set
    too tight.
    """
    if app_settings.allow_unsigned_init_data:
        pytest.skip("HMAC bypassed in this test config")
    recent = int(time.time()) - 14 * 60  # 14 min in the past
    init = _signed_init_data_with_auth_date(9105, recent, "recent9105")
    parsed = verify_init_data(init)
    assert parsed["id"] == 9105


def test_init_data_max_age_is_configurable(monkeypatch):
    """``settings.init_data_max_age_seconds`` is read at every
    ``verify_init_data`` call (not snapshotted at import). Setting a
    60-second window must reject a 120-second-old token and accept a
    30-second-old one.
    """
    if app_settings.allow_unsigned_init_data:
        pytest.skip("HMAC bypassed in this test config")
    monkeypatch.setattr(app_settings, "init_data_max_age_seconds", 60)

    too_old = int(time.time()) - 120  # 2 min in the past, beyond 60s window
    init_old = _signed_init_data_with_auth_date(9106, too_old, "cfg_old9106")
    with pytest.raises(InitDataError) as exc:
        verify_init_data(init_old)
    assert "expired" in str(exc.value).lower()

    fresh = int(time.time()) - 30  # 30 sec in the past, within 60s window
    init_fresh = _signed_init_data_with_auth_date(9107, fresh, "cfg_fresh9107")
    parsed = verify_init_data(init_fresh)
    assert parsed["id"] == 9107


# --- M5: Decimal end-to-end in money paths ---------------------------------


@pytest.mark.asyncio
async def test_debit_preserves_decimal_precision():
    """Eight-decimal-place crypto amounts survive a debit unchanged.

    Pre-fix ``_debit`` did ``bal.amount = float(Decimal(...) - amount)``;
    a starting balance of ``1234567.12345678`` minus ``0.00000001``
    would come back as ``1234567.12345677`` or worse depending on
    binary-float rounding. The fix keeps the value as ``Decimal``,
    so the read-back is exact.
    """
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        user = User(tg_user_id=5501, username="m5_debit5501", display_name="m5")
        session.add(user)
        await session.flush()

        bal = await get_or_create_balance(session, user.id, usdt.id)
        bal.amount = Decimal("1234567.12345678")
        bal.locked = Decimal(0)
        await session.commit()

        await _debit(session, user.id, usdt.id, Decimal("0.00000001"))
        await session.commit()
        await session.refresh(bal)

    assert Decimal(str(bal.amount)) == Decimal("1234567.12345677"), bal.amount
    assert Decimal(str(bal.locked)) == Decimal("0.00000001"), bal.locked


@pytest.mark.asyncio
async def test_release_preserves_decimal_precision_across_round_trip():
    """A complete debit → release round-trip on the same currency
    returns the buyer to *exactly* their starting amount when no
    commission is taken (``locked_amount == payout_amount``).
    """
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        payer = User(tg_user_id=5502, username="m5_payer5502", display_name="m5p")
        payee = User(tg_user_id=5503, username="m5_payee5503", display_name="m5q")
        session.add_all([payer, payee])
        await session.flush()

        start = Decimal("9876543.21000007")
        amount = Decimal("0.00000005")
        bal = await get_or_create_balance(session, payer.id, usdt.id)
        bal.amount = start
        bal.locked = Decimal(0)
        await session.commit()

        await _debit(session, payer.id, usdt.id, amount)
        await _release_to(session, payer.id, payee.id, usdt.id, amount, amount)
        await session.commit()

        payer_bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == payer.id, UserBalance.currency_id == usdt.id
                )
            )
        ).scalar_one()
        payee_bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == payee.id, UserBalance.currency_id == usdt.id
                )
            )
        ).scalar_one()

    # Payer is fully unlocked (commission == 0 in this scenario) and
    # the principal stayed with their original balance minus
    # ``amount``; payee has gained exactly ``amount``.
    assert Decimal(str(payer_bal.amount)) == start - amount
    assert Decimal(str(payer_bal.locked)) == Decimal(0)
    assert Decimal(str(payee_bal.amount)) == amount


@pytest.mark.asyncio
async def test_refund_preserves_decimal_precision():
    """A locked-then-refunded crypto amount round-trips through the
    ledger with zero loss.
    """
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        user = User(tg_user_id=5504, username="m5_refund5504", display_name="m5r")
        session.add(user)
        await session.flush()

        bal = await get_or_create_balance(session, user.id, usdt.id)
        bal.amount = Decimal("100.00000000")
        bal.locked = Decimal(0)
        await session.commit()

        await _debit(session, user.id, usdt.id, Decimal("12.34567891"))
        await _refund(session, user.id, usdt.id, Decimal("12.34567891"))
        await session.commit()
        await session.refresh(bal)

    assert Decimal(str(bal.amount)) == Decimal("100.00000000")
    assert Decimal(str(bal.locked)) == Decimal(0)
