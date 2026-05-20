"""Comment 31 (H, anti-griefing) — ``users.deals_total`` regression.

Pre-fix, ``create_deal`` bumped ``seller.deals_total`` on every
``POST /api/deals``. The seller could not refuse fast enough: even at
the ``RLDealCreate = 10/60s`` rate-limit, ten attempts per minute
across multiple buyers visibly inflate the seller's public profile
metric (the "сделок: N" counter on every user card) without the seller
ever agreeing to a deal. Worse, the inflated counter sticks until the
seller manually cancels each one.

Fix: move the ``deals_total += 1`` increment from ``create_deal`` to
``accept_deal``. Once the seller actively accepts, both sides earn the
metric bump; until then a pending row is just a "request" and doesn't
count.

This test exercises three transitions:

1. Creating a deal must NOT increment either party's ``deals_total``.
2. Accepting it must increment BOTH buyer and seller by 1.
3. Declining a freshly created deal also must NOT increment anyone —
   a malicious buyer cannot inflate seller.deals_total by spam-creating
   deals the seller declines.
"""

from __future__ import annotations

from sqlalchemy import select

from tests.helpers import (
    auth_headers,
    credit_balance,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)


async def _create_deal(client, *, buyer_tg: int, seller_tg: int) -> tuple[int, str, str, str, str]:
    """Bootstrap a buyer+seller pair and return a fresh pending deal.

    Returns ``(deal_id, buyer_init, seller_init, buyer_pin, seller_pin)``.
    """
    from backend.app.db import async_session

    buyer_init = signed_init_data(buyer_tg, f"grief_buyer_{buyer_tg}")
    seller_init = signed_init_data(seller_tg, f"grief_seller_{seller_tg}")
    buyer_pin = await setup_pin(client, buyer_init)
    seller_pin = await setup_pin(client, seller_init)

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, buyer_tg)
        await credit_balance(session, buyer_id, "USDT", 50)

    create_resp = await client.post(
        "/api/deals",
        json={
            "counterparty": f"grief_seller_{seller_tg}",
            "role": "buyer",
            "amount": 10,
            "description": "anti-grief regression",
            "pay_comission": "buyer",
            "currency_code": "USDT",
        },
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    assert create_resp.status_code == 201, create_resp.text
    return create_resp.json()["id"], buyer_init, seller_init, buyer_pin, seller_pin


async def test_create_deal_does_not_inflate_deals_total(client):
    """Comment 31 — creating a deal must NOT touch ``deals_total``.

    Pre-fix the seller's counter would already read ``1`` here even
    though they have not yet accepted (or even seen) the deal.
    """
    from backend.app.db import async_session
    from backend.app.models import User

    _deal_id, _buyer_init, _seller_init, _buyer_pin, _seller_pin = await _create_deal(
        client, buyer_tg=4001, seller_tg=4002
    )

    async with async_session() as session:
        buyer = (await session.execute(select(User).where(User.tg_user_id == 4001))).scalar_one()
        seller = (await session.execute(select(User).where(User.tg_user_id == 4002))).scalar_one()
        assert buyer.deals_total == 0, buyer.deals_total
        assert seller.deals_total == 0, seller.deals_total


async def test_accept_deal_increments_both_sides(client):
    """Comment 31 — once the seller accepts, both buyer and seller
    earn ``deals_total += 1``. The increment is symmetric (the
    metric counts "deals participated in" for both roles)."""
    from backend.app.db import async_session
    from backend.app.models import User

    deal_id, _buyer_init, seller_init, _buyer_pin, seller_pin = await _create_deal(
        client, buyer_tg=4011, seller_tg=4012
    )

    accept_resp = await client.post(
        f"/api/deals/{deal_id}/accept",
        headers={**auth_headers(seller_init), "X-Pin-Token": seller_pin},
    )
    assert accept_resp.status_code == 200, accept_resp.text

    async with async_session() as session:
        buyer = (await session.execute(select(User).where(User.tg_user_id == 4011))).scalar_one()
        seller = (await session.execute(select(User).where(User.tg_user_id == 4012))).scalar_one()
        assert buyer.deals_total == 1
        assert seller.deals_total == 1


async def test_decline_deal_does_not_inflate_deals_total(client):
    """Comment 31 — a deal the seller declines must leave both sides
    on zero. This is the exact harassment vector the fix targets: a
    griefer creates 10 deals against a victim seller (the
    ``RLDealCreate`` ceiling), the victim declines all 10, but the
    seller's public profile counter still inflates by 10. Post-fix
    the counter stays at 0 because the increment lives in
    ``accept_deal``, not ``create_deal``.
    """
    from backend.app.db import async_session
    from backend.app.models import User

    deal_id, _buyer_init, seller_init, _buyer_pin, seller_pin = await _create_deal(
        client, buyer_tg=4021, seller_tg=4022
    )

    decline_resp = await client.post(
        f"/api/deals/{deal_id}/decline",
        headers={**auth_headers(seller_init), "X-Pin-Token": seller_pin},
    )
    assert decline_resp.status_code == 200, decline_resp.text

    async with async_session() as session:
        buyer = (await session.execute(select(User).where(User.tg_user_id == 4021))).scalar_one()
        seller = (await session.execute(select(User).where(User.tg_user_id == 4022))).scalar_one()
        assert buyer.deals_total == 0
        assert seller.deals_total == 0
