"""Audit H1 regression — ``_accrued_by_currency`` ignores commission
on terminal deals where it was never actually collected.

Background
----------

A deal with ``pay_commission = seller`` only locks ``amount`` from
the buyer at ``create_deal`` time (not ``amount + commission``).  The
commission is taken from the *seller's* payout once the deal reaches
``completed`` / ``resolved_for_seller``.  Therefore on any terminal
status that is **not** in the seller's favour — ``cancelled``,
``cancelled_for_inactivity``, ``resolved_for_buyer`` — the buyer is
refunded the whole locked ``amount`` and the seller never pays
anything.  No real commission landed in the treasury.

Pre-fix the treasury overview summed
``Deal.commission_amount`` for every terminal deal, treating those
phantom amounts as collected.  ``GET /api/admin/treasury`` therefore
reported a positive ``accrued`` figure that wasn't backed by any
on-platform balance change, and ``POST /api/admin/treasury/withdraw``
would happily move funds out of the treasury that never landed
there — a direct accounting deficit against the real per-user
wallet balances.

The fix filters the SQL aggregation so commission counts only when
either:

* the seller actually got paid out (status in
  ``completed`` / ``resolved_for_seller``), or
* the buyer paid the commission upfront (``pay_commission = buyer``)
  and it stayed with the platform after a refund.

This file is the regression for that filter.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import Currency, Deal, DealStatus, PayCommission, User
from tests.helpers import auth_headers, signed_init_data


async def _bootstrap(client, *, tg_user_id: int, username: str) -> int:
    init = signed_init_data(tg_user_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _make_admin(client, tg: int) -> str:
    init = signed_init_data(tg, f"h1_admin{tg}")
    uid = await _bootstrap(client, tg_user_id=tg, username=f"h1_admin{tg}")
    async with async_session() as session:
        u = await session.get(User, uid)
        assert u is not None
        u.is_admin = True
        await session.commit()
    return init


async def _seed_deal(
    *,
    buyer_id: int,
    seller_id: int,
    status: DealStatus,
    pay_commission: PayCommission,
    commission: Decimal,
    amount: Decimal = Decimal("100"),
) -> None:
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        session.add(
            Deal(
                buyer_id=buyer_id,
                seller_id=seller_id,
                currency_id=usdt.id,
                amount=amount,
                commission_amount=commission,
                pay_commission=pay_commission,
                status=status,
                description=f"H1 seed {status.value} / {pay_commission.value}",
            )
        )
        await session.commit()


@pytest.mark.parametrize(
    "status",
    [
        DealStatus.cancelled,
        DealStatus.cancelled_for_inactivity,
        DealStatus.resolved_for_buyer,
    ],
)
async def test_seller_paid_commission_not_accrued_on_buyer_refund(client, status):
    """Audit H1 — a deal that ended ``not in the seller's favour`` AND
    had ``pay_commission=seller`` must NOT contribute to ``accrued``.

    Pre-fix the treasury overview reported a phantom ``accrued`` of
    ``commission_amount`` here even though no money changed hands on
    the commission line.
    """
    admin_init = await _make_admin(client, tg=9001)
    buyer = await _bootstrap(client, tg_user_id=9002, username="h1_buyer")
    seller = await _bootstrap(client, tg_user_id=9003, username="h1_seller")

    await _seed_deal(
        buyer_id=buyer,
        seller_id=seller,
        status=status,
        pay_commission=PayCommission.seller,
        commission=Decimal("5"),
    )

    resp = await client.get("/api/admin/treasury", headers=auth_headers(admin_init))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    usdt = next(b for b in body["balances"] if b["currency_code"] == "USDT")
    assert Decimal(str(usdt["accrued"])) == Decimal("0"), (
        f"accrued must be 0 for status={status.value}, pay_commission=seller, got {usdt['accrued']}"
    )
    assert Decimal(str(usdt["available"])) == Decimal("0")


async def test_seller_paid_commission_accrued_only_when_seller_paid(client):
    """Audit H1 — ``pay_commission=seller`` deals DO contribute to
    ``accrued`` once they end ``completed`` / ``resolved_for_seller``.
    That's the path where the commission was actually withheld from
    the seller's payout.
    """
    admin_init = await _make_admin(client, tg=9011)
    buyer = await _bootstrap(client, tg_user_id=9012, username="h1_buyer2")
    seller = await _bootstrap(client, tg_user_id=9013, username="h1_seller2")

    await _seed_deal(
        buyer_id=buyer,
        seller_id=seller,
        status=DealStatus.completed,
        pay_commission=PayCommission.seller,
        commission=Decimal("7"),
    )
    await _seed_deal(
        buyer_id=buyer,
        seller_id=seller,
        status=DealStatus.resolved_for_seller,
        pay_commission=PayCommission.seller,
        commission=Decimal("3"),
    )

    resp = await client.get("/api/admin/treasury", headers=auth_headers(admin_init))
    body = resp.json()
    usdt = next(b for b in body["balances"] if b["currency_code"] == "USDT")
    assert Decimal(str(usdt["accrued"])) == Decimal("10")


@pytest.mark.parametrize(
    "status",
    [
        DealStatus.completed,
        DealStatus.cancelled,
        DealStatus.cancelled_for_inactivity,
        DealStatus.resolved_for_buyer,
        DealStatus.resolved_for_seller,
    ],
)
async def test_buyer_paid_commission_always_accrued(client, status):
    """Audit H1 — ``pay_commission=buyer`` deals always count.

    The buyer's lock at creation already included the commission, so
    on any refund path the platform keeps the commission (the
    services_deals refund code returns only ``amount`` to the buyer).
    """
    # Each parametrize run is a fresh DB (the ``reset_db`` autouse
    # fixture truncates between tests), so fixed IDs are safe.
    admin_init = await _make_admin(client, tg=9020)
    buyer = await _bootstrap(client, tg_user_id=9021, username="h1_buyer_bp")
    seller = await _bootstrap(client, tg_user_id=9022, username="h1_seller_bp")

    await _seed_deal(
        buyer_id=buyer,
        seller_id=seller,
        status=status,
        pay_commission=PayCommission.buyer,
        commission=Decimal("4"),
    )

    resp = await client.get("/api/admin/treasury", headers=auth_headers(admin_init))
    body = resp.json()
    usdt = next(b for b in body["balances"] if b["currency_code"] == "USDT")
    assert Decimal(str(usdt["accrued"])) == Decimal("4"), (
        f"buyer-paid commission must be accrued for status={status.value}, got {usdt['accrued']}"
    )


async def test_mixed_population_accrues_only_real_commission(client):
    """Audit H1 — end-to-end mixed seed: three deals, only the two
    where commission was actually collected contribute to ``accrued``.
    """
    admin_init = await _make_admin(client, tg=9050)
    buyer = await _bootstrap(client, tg_user_id=9051, username="h1_mixed_b")
    seller = await _bootstrap(client, tg_user_id=9052, username="h1_mixed_s")

    # Phantom — seller-paid commission on a buyer refund. Must NOT
    # contribute.
    await _seed_deal(
        buyer_id=buyer,
        seller_id=seller,
        status=DealStatus.cancelled,
        pay_commission=PayCommission.seller,
        commission=Decimal("100"),
    )
    # Real — buyer-paid commission on a cancellation. The buyer's
    # lock retained the commission line. Counts.
    await _seed_deal(
        buyer_id=buyer,
        seller_id=seller,
        status=DealStatus.cancelled,
        pay_commission=PayCommission.buyer,
        commission=Decimal("2"),
    )
    # Real — seller-paid commission on a completed deal. Counts.
    await _seed_deal(
        buyer_id=buyer,
        seller_id=seller,
        status=DealStatus.completed,
        pay_commission=PayCommission.seller,
        commission=Decimal("3"),
    )

    resp = await client.get("/api/admin/treasury", headers=auth_headers(admin_init))
    body = resp.json()
    usdt = next(b for b in body["balances"] if b["currency_code"] == "USDT")
    assert Decimal(str(usdt["accrued"])) == Decimal("5"), usdt
