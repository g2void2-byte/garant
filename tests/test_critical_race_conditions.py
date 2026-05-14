"""Regression tests for the three Critical findings in the May code review:

* **C1** ``create_withdrawal`` race-condition — two concurrent withdraw
  requests against the same balance must not both succeed when the user
  doesn't have enough funds for both.
* **C2** ``create_deal`` / ``_debit`` race-condition — two concurrent
  deal-creation requests against the same buyer balance must not both
  succeed when the user doesn't have enough funds for both.
* **C3** ``manual_deposit`` 500 — two requests with the same amount must
  not collide on ``provider_invoice_id`` and bubble up an
  ``IntegrityError``.

The fix for C1 and C2 is a ``FOR UPDATE`` row lock on ``UserBalance``;
the fix for C3 is a UUID-suffixed ``provider_invoice_id``.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from .helpers import auth_headers, credit_balance, get_user_id_by_tg, setup_pin, signed_init_data


@pytest.mark.asyncio
async def test_concurrent_withdrawals_cannot_overdraw(client):
    """C1 — two parallel withdrawals of >½ balance must not both succeed.

    The user has 100 USDT; two simultaneous 70-USDT withdrawal requests
    arrive. Without the ``FOR UPDATE`` lock both pass the
    ``bal.amount >= amount`` check, both succeed, and the balance ends
    at -40. With the lock one of them sees the post-debit balance and
    fails with 400 ("Недостаточно средств").
    """
    from backend.app.db import async_session
    from backend.app.models import Currency, UserBalance

    init = signed_init_data(7101, "race_withdraw")
    pin_token = await setup_pin(client, init)

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 7101)
        await credit_balance(session, user_id, "USDT", 100.0)

    headers = {**auth_headers(init), "X-Pin-Token": pin_token}
    body = {"currency_code": "USDT", "amount": 70.0, "address": "TXyz123456789abcdef"}

    r1, r2 = await asyncio.gather(
        client.post("/api/wallet/withdrawals", json=body, headers=headers),
        client.post("/api/wallet/withdrawals", json=body, headers=headers),
    )

    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 400], (r1.status_code, r1.text, r2.status_code, r2.text)

    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == user_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        # Spendable balance ends at 30 (= 100 − 70), the other request
        # was rejected. Locked holds the queued withdrawal.
        assert float(bal.amount) == 30.0
        assert float(bal.locked) == 70.0


@pytest.mark.asyncio
async def test_concurrent_deal_creation_cannot_overdraw(client):
    """C2 — two parallel ``create_deal`` requests must not overspend.

    Buyer has 100 USDT; two simultaneous deals of 70 USDT each are
    submitted. Each costs 70 + 5% commission = 73.5 locked. Without the
    ``FOR UPDATE`` lock on ``_debit`` both pass the balance check; with
    the lock one returns 400 ("Недостаточно средств").
    """
    from backend.app.db import async_session
    from backend.app.models import Currency, UserBalance

    buyer_init = signed_init_data(7201, "race_buyer")
    seller_init = signed_init_data(7202, "race_seller")
    buyer_pin = await setup_pin(client, buyer_init)
    await setup_pin(client, seller_init)

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 7201)
        await credit_balance(session, buyer_id, "USDT", 100.0)

    headers = {**auth_headers(buyer_init), "X-Pin-Token": buyer_pin}
    body = {
        "counterparty": "race_seller",
        "role": "buyer",
        "sum": 70.0,
        "description": "race test",
        "pay_comission": "buyer",
        "currency_code": "USDT",
    }

    r1, r2 = await asyncio.gather(
        client.post("/api/deals", json=body, headers=headers),
        client.post("/api/deals", json=body, headers=headers),
    )

    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [201, 400], (r1.status_code, r1.text, r2.status_code, r2.text)

    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == buyer_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        # Only one deal got debited: 100 − 73.5 = 26.5 spendable,
        # 73.5 locked. The balance must never go negative.
        assert float(bal.amount) >= 0
        assert float(bal.amount) == pytest.approx(26.5)
        assert float(bal.locked) == pytest.approx(73.5)


@pytest.mark.asyncio
async def test_manual_deposit_same_amount_does_not_collide(client):
    """C3 — repeated ``POST /api/payments/deposit`` with identical amount
    must not blow up on the ``provider_invoice_id`` UNIQUE constraint.

    Before the fix the row id was ``manual-{user.id}-{amount}``, so two
    requests for the same amount within the rate-limit window raised
    ``IntegrityError`` → 500. The UUID suffix removes the collision.
    """
    init = signed_init_data(7301, "manual_dep")
    await client.get("/api/me", headers=auth_headers(init))

    r1 = await client.post(
        "/api/payments/deposit", json={"amount": 25.0}, headers=auth_headers(init)
    )
    r2 = await client.post(
        "/api/payments/deposit", json={"amount": 25.0}, headers=auth_headers(init)
    )

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r1.json()["id"] != r2.json()["id"]
