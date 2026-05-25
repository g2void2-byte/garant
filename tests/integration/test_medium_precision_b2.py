"""Audit fix for PR B2 — Decimal wire format on admin read paths (M-3 / M-9).

Coverage:

* Admin response amount fields serialise as **JSON strings** so callers
  see full ``Decimal`` precision (Pydantic v2 default behaviour for
  ``Decimal`` is ``str`` in JSON output). The previous schema typed
  these fields as ``float`` and the routers explicitly cast with
  ``float(...)`` — a round-trip that silently dropped trailing satoshi
  on large BTC amounts.
* Endpoints covered: ``/api/admin/wallets/{user_id}``,
  ``/api/admin/deposits``, ``/api/admin/withdrawals``. The frontend
  has a matching ``parseDecimal`` helper that accepts
  ``string | number``. The legacy ``/api/admin/treasury`` overview
  was removed by P5 — commission accrual is now per-deal via the
  buyer's deposit invoice (see ``services_deals.create_deal_with_topup``).
"""

from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import (
    Currency,
    User,
    UserBalance,
    WalletDeposit,
    WalletDepositStatus,
    WalletWithdrawal,
    WalletWithdrawStatus,
)
from tests.helpers import (
    auth_headers,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)


async def _make_admin(client, tg_id: int = 9001, username: str = "admin") -> str:
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


# ── /api/admin/wallets/{user_id} ───────────────────────────────────────────


async def test_admin_user_balances_amounts_are_json_strings(client):
    """Balance amount/locked/total come back as JSON strings.

    Regression: if the schema reverts to ``float``, large BTC amounts
    lose their last few satoshi at JSON-serialise time.
    """
    target_init = signed_init_data(7780, "btc_user")
    await setup_pin(client, target_init)
    admin_init = await _make_admin(client)

    btc_amount = Decimal("1.23456789")
    btc_locked = Decimal("0.00000001")

    async with async_session() as session:
        uid = await get_user_id_by_tg(session, 7780)
        btc = (await session.execute(select(Currency).where(Currency.code == "BTC"))).scalar_one()
        bal = UserBalance(
            user_id=uid,
            currency_id=btc.id,
            amount=btc_amount,
            locked=btc_locked,
        )
        session.add(bal)
        await session.commit()

    resp = await client.get(f"/api/admin/wallets/{uid}", headers=auth_headers(admin_init))
    assert resp.status_code == 200, resp.text
    # Inspect raw JSON, not the parsed dict — confirms wire format.
    parsed = json.loads(resp.content)
    btc_row = next(r for r in parsed if r["currency_code"] == "BTC")
    assert isinstance(btc_row["amount"], str)
    assert isinstance(btc_row["locked"], str)
    assert isinstance(btc_row["total"], str)
    assert Decimal(btc_row["amount"]) == btc_amount
    assert Decimal(btc_row["locked"]) == btc_locked
    assert Decimal(btc_row["total"]) == btc_amount + btc_locked


# ── /api/admin/deposits ────────────────────────────────────────────────────


async def test_admin_deposits_amount_is_json_string(client):
    target_init = signed_init_data(7781, "dep_user")
    await setup_pin(client, target_init)
    admin_init = await _make_admin(client)

    async with async_session() as session:
        uid = await get_user_id_by_tg(session, 7781)
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        dep = WalletDeposit(
            user_id=uid,
            currency_id=usdt.id,
            amount=Decimal("12.50"),
            status=WalletDepositStatus.pending,
            provider_invoice_id="inv-precision-1",
            pay_url="https://example/pay",
        )
        session.add(dep)
        await session.commit()

    resp = await client.get("/api/admin/deposits", headers=auth_headers(admin_init))
    assert resp.status_code == 200, resp.text
    parsed = json.loads(resp.content)
    item = next(it for it in parsed["items"] if it["provider_invoice_id"] == "inv-precision-1")
    assert isinstance(item["amount"], str)
    assert Decimal(item["amount"]) == Decimal("12.50")


# ── /api/admin/withdrawals ─────────────────────────────────────────────────


async def test_admin_withdrawals_amount_is_json_string(client):
    target_init = signed_init_data(7782, "wd_user")
    await setup_pin(client, target_init)
    admin_init = await _make_admin(client)

    async with async_session() as session:
        uid = await get_user_id_by_tg(session, 7782)
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        wd = WalletWithdrawal(
            user_id=uid,
            currency_id=usdt.id,
            amount=Decimal("7.42"),
            address="TXyz-precision-fixture",
            status=WalletWithdrawStatus.pending,
        )
        session.add(wd)
        await session.commit()

    resp = await client.get("/api/admin/withdrawals", headers=auth_headers(admin_init))
    assert resp.status_code == 200, resp.text
    parsed = json.loads(resp.content)
    item = next(it for it in parsed["items"] if it["address"] == "TXyz-precision-fixture")
    assert isinstance(item["amount"], str)
    assert Decimal(item["amount"]) == Decimal("7.42")
