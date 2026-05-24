"""Automatic cancellation of stale ``pending_confirmation`` deals."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from tests.helpers import (
    auth_headers,
    credit_balance,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)


async def test_sweep_cancels_stale_pending_confirmation(client):
    from backend.app.db import async_session
    from backend.app.models import Currency, Deal, DealStatus, UserBalance
    from backend.app.services_deals import sweep_inactivity

    buyer_init = signed_init_data(5001, "buyer5")
    seller_init = signed_init_data(5002, "seller5")
    buyer_pin = await setup_pin(client, buyer_init)
    await setup_pin(client, seller_init)

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 5001)
        await credit_balance(session, buyer_id, "USDT", 100)

    deal_id = (
        await client.post(
            "/api/deals",
            json={
                "counterparty": "seller5",
                "role": "buyer",
                "amount": 30,
                "currency_code": "USDT",
            },
            headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
        )
    ).json()["id"]

    # Backdate ``created_at`` past the default inactivity_pending_confirmation_days=7.
    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        from backend.app.time_utils import utcnow

        deal.created_at = utcnow() - dt.timedelta(days=30)
        await session.commit()

        affected = await sweep_inactivity(session)
        assert affected == 1

    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        assert deal.status == DealStatus.cancelled_for_inactivity

        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == buyer_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        # P10 — commission is no longer locked on the legacy
        # ``POST /api/deals`` path, so the inactivity sweep refunds
        # the buyer the full 30 principal 1:1.
        assert float(bal.amount) == 100.0
        assert float(bal.locked) == 0.0
