"""Audit fixes for PR B1 — money/precision on admin write paths.

Coverage:

* **M-20** — ``routers/admin/wallets.py:_balance_row`` keeps balance
  arithmetic in ``Decimal`` so the response ``total`` doesn't surface
  float64 round-trip errors (``0.1 + 0.2 == 0.30000000000000004``).
* **M-23** — ``routers/admin/deals.py`` admin delete-deal restores
  locked funds to the buyer's ``Numeric(18,8)`` balance using
  ``Decimal`` directly. The previous ``float(...)`` wrapper round-tripped
  through float64 and dropped trailing satoshi on large BTC balances.
  The audit-log JSONB payload also now stores amounts as strings.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import (
    AdminAuditLog,
    Currency,
    Deal,
    DealStatus,
    PayCommission,
    User,
    UserBalance,
)
from tests.helpers import (
    auth_headers,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
    with_totp,
)


async def _make_admin(client, tg_id: int = 9001, username: str = "admin") -> str:
    """Mint an authenticated admin user the same way ``test_admin_deals`` does."""
    init = signed_init_data(tg_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200
    uid = resp.json()["id"]
    async with async_session() as session:
        user = await session.get(User, uid)
        assert user is not None
        user.is_admin = True
        await session.commit()
    return init


# ── M-20: ``_balance_row`` keeps Decimal arithmetic ─────────────────────────


async def test_admin_wallet_total_uses_decimal_arithmetic(client):
    """``_balance_row.total`` is computed in ``Decimal`` so the response
    doesn't surface ``0.1 + 0.2 == 0.30000000000000004``.

    Old (buggy) code did ``float(bal.amount) + float(bal.locked)``; the
    new code keeps the operands as Decimals and lets Pydantic coerce at
    the schema boundary.
    """
    target_init = signed_init_data(7777, "wallet_user")
    await setup_pin(client, target_init)
    admin_init = await _make_admin(client)
    async with async_session() as session:
        uid = await get_user_id_by_tg(session, 7777)
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        # 0.1 + 0.2 is the canonical float surface-error example. Both
        # values fit USDT's 2-decimal precision so this isn't about
        # truncation — it's purely about the choice of arithmetic.
        bal = UserBalance(
            user_id=uid,
            currency_id=usdt.id,
            amount=Decimal("0.10"),
            locked=Decimal("0.20"),
        )
        session.add(bal)
        await session.commit()

    resp = await client.get(f"/api/admin/wallets/{uid}", headers=auth_headers(admin_init))
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    usdt_row = next(r for r in rows if r["currency_code"] == "USDT")
    # If the server used float arithmetic, ``total`` would surface as
    # 0.30000000000000004 — Pydantic happily serialises that.
    # Decimal is serialised as a string in Pydantic v2 JSON output.
    assert Decimal(usdt_row["total"]) == Decimal("0.30")
    assert Decimal(usdt_row["amount"]) == Decimal("0.10")
    assert Decimal(usdt_row["locked"]) == Decimal("0.20")


async def test_admin_wallet_total_handles_missing_balance(client):
    """A user with no ``UserBalance`` row reads as a clean zero."""
    target_init = signed_init_data(7778, "empty_user")
    await setup_pin(client, target_init)
    admin_init = await _make_admin(client)
    async with async_session() as session:
        uid = await get_user_id_by_tg(session, 7778)
    resp = await client.get(f"/api/admin/wallets/{uid}", headers=auth_headers(admin_init))
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    for row in rows:
        assert Decimal(row["amount"]) == Decimal(0)
        assert Decimal(row["locked"]) == Decimal(0)
        assert Decimal(row["total"]) == Decimal(0)


# ── M-23: admin delete-deal writes Decimals to Numeric(18,8) columns ────────


# A value that round-trips lossily through float64: 18 significant
# digits, beyond IEEE-754 double's ~15.95 digits of mantissa. The
# old ``float(...)`` cast collapses it to 1234567890.1234567 (last
# satoshi truncated). Numeric(18,8) holds it exactly.
_BTC_LOSSY = Decimal("1234567890.12345678")


async def _seed_btc_deal_in_progress(buyer_tg: int, seller_tg: int) -> int:
    """Create an in-progress BTC deal with ``_BTC_LOSSY`` locked from buyer.

    Bypasses the public /api/deals creation flow because that uses Decimal
    end-to-end and is bounded by ``Deal.sum`` (Numeric(14,2)). We need a
    BTC ``Numeric(28,8)`` amount that surfaces float-round-trip loss.
    """
    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, buyer_tg)
        seller_id = await get_user_id_by_tg(session, seller_tg)
        btc = (await session.execute(select(Currency).where(Currency.code == "BTC"))).scalar_one()
        # Lock the deal amount on the buyer's BTC balance (no commission
        # for this test — keeps the maths simple).
        bal = UserBalance(
            user_id=buyer_id,
            currency_id=btc.id,
            amount=Decimal(0),
            locked=_BTC_LOSSY,
        )
        session.add(bal)
        await session.flush()
        deal = Deal(
            buyer_id=buyer_id,
            seller_id=seller_id,
            sum=Decimal("1.00"),
            description="precision regression fixture",
            pay_commission=PayCommission.seller,
            status=DealStatus.in_progress,
            confirm_buyer=False,
            confirm_seller=False,
            currency_id=btc.id,
            amount=_BTC_LOSSY,
            commission_amount=Decimal(0),
        )
        session.add(deal)
        await session.commit()
        return deal.id


async def test_admin_delete_deal_preserves_btc_satoshi_precision(client):
    """Admin delete refunds the locked pot to ``buyer_balance.amount``
    without losing a satoshi to float64 round-trip.

    Regression: ``deals.py:836-839`` previously wrote
    ``buyer_balance.amount = float(...)`` which collapses Decimals beyond
    ~15.95 sig digits. Numeric(18,8) supports the full Decimal range.
    """
    buyer_init = signed_init_data(8001, "buyer_btc")
    seller_init = signed_init_data(8002, "seller_btc")
    await setup_pin(client, buyer_init)
    await setup_pin(client, seller_init)
    deal_id = await _seed_btc_deal_in_progress(8001, 8002)

    admin_init = await _make_admin(client)
    resp = await client.post(
        f"/api/admin/deals/{deal_id}/delete",
        json={"reason": "regression fixture"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 8001)
        btc = (await session.execute(select(Currency).where(Currency.code == "BTC"))).scalar_one()
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == buyer_id,
                    UserBalance.currency_id == btc.id,
                )
            )
        ).scalar_one()

    # The locked pot moves from locked -> amount atomically. The exact
    # Decimal must survive both reads and writes. With the old float
    # cast, ``bal.amount`` would be ``Decimal('1234567890.12345670')`` —
    # one satoshi short.
    assert bal.amount == _BTC_LOSSY
    assert bal.locked == Decimal(0)


async def test_admin_delete_deal_audit_payload_is_string(client):
    """Audit payload stores amount columns as strings so JSONB keeps
    the full Decimal precision (not a float that drops trailing
    satoshi at JSON-serialize time).
    """
    buyer_init = signed_init_data(8003, "buyer_btc2")
    seller_init = signed_init_data(8004, "seller_btc2")
    await setup_pin(client, buyer_init)
    await setup_pin(client, seller_init)
    deal_id = await _seed_btc_deal_in_progress(8003, 8004)

    admin_init = await _make_admin(client)
    await client.post(
        f"/api/admin/deals/{deal_id}/delete",
        json={"reason": "audit precision"},
        headers=with_totp(auth_headers(admin_init)),
    )
    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(AdminAuditLog).where(AdminAuditLog.action == "deal.delete")
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    payload = rows[0].payload
    assert payload is not None
    # All amount columns now serialised as strings — the value is the
    # Decimal's canonical form, not a float repr.
    assert payload["amount"] == str(_BTC_LOSSY)
    assert payload["refunded"] == str(_BTC_LOSSY)
    assert payload["sum"] == "1.00"
    # ``commission_amount`` stored as ``Decimal(0)`` round-trips as some
    # Decimal-shaped string ("0", "0E-8", ...). What matters is that it's
    # NOT a float and NOT lossy when parsed back.
    assert isinstance(payload["commission_amount"], str)
    assert Decimal(payload["commission_amount"]) == Decimal(0)


async def test_admin_wallet_adjust_audit_payload_is_string(client):
    """``log_admin_action`` payload for wallet adjustments stores
    deltas as strings — keeps the audit trail Decimal-precise.

    Regression target: ``adjust_user_balance`` previously did
    ``float(delta)`` / ``float(before_amount)`` which would clip
    trailing satoshi on large BTC adjustments.
    """
    target_init = signed_init_data(7779, "adjust_user")
    await setup_pin(client, target_init)
    admin_init = await _make_admin(client)
    async with async_session() as session:
        uid = await get_user_id_by_tg(session, 7779)

    delta = "0.12345678"  # full 8-decimal precision
    resp = await client.post(
        f"/api/admin/wallets/{uid}/adjust",
        json={"currency_code": "BTC", "amount": delta, "reason": "test"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text

    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(AdminAuditLog).where(AdminAuditLog.action == "wallet.adjust")
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    payload = rows[0].payload
    assert payload is not None
    assert payload["delta"] == "0.12345678"
    # Before/after stored as Decimal-canonical strings; exact form
    # (``"0"`` vs ``"0E-8"``) depends on DB round-trip but both parse
    # back to the same Decimal.
    assert isinstance(payload["before_amount"], str)
    assert Decimal(payload["before_amount"]) == Decimal(0)
    assert isinstance(payload["after_amount"], str)
    assert Decimal(payload["after_amount"]) == Decimal("0.12345678")
