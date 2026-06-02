"""Regression coverage for user-facing deal-list query validation."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import Currency, Deal, DealStatus, User
from backend.app.time_utils import utcnow
from tests.helpers import auth_headers, signed_init_data


async def test_deals_list_rejects_unknown_role_and_status(client):
    """Invalid filters must be typed 422s, not silently ignored.

    Pre-fix ``role=all`` or ``status=wat`` fell through and returned the
    requester's unfiltered deal list, which made frontend/filter typos look
    like valid broad queries.
    """
    init = signed_init_data(51001, "deal_filter_user")

    role_resp = await client.get("/api/deals?role=all", headers=auth_headers(init))
    assert role_resp.status_code == 422, role_resp.text

    status_resp = await client.get("/api/deals?status=wat", headers=auth_headers(init))
    assert status_resp.status_code == 422, status_resp.text


async def test_deals_list_supports_limit_offset(client):
    init = signed_init_data(51002, "deal_page_buyer")
    seller_init = signed_init_data(51003, "deal_page_seller")
    buyer_resp = await client.get("/api/me", headers=auth_headers(init))
    seller_resp = await client.get("/api/me", headers=auth_headers(seller_init))
    assert buyer_resp.status_code == 200, buyer_resp.text
    assert seller_resp.status_code == 200, seller_resp.text

    async with async_session() as session:
        buyer = (
            await session.execute(select(User).where(User.username == "deal_page_buyer"))
        ).scalar_one()
        seller = (
            await session.execute(select(User).where(User.username == "deal_page_seller"))
        ).scalar_one()
        currency = (
            await session.execute(select(Currency).where(Currency.code == "USDT"))
        ).scalar_one()
        now = utcnow()
        deals = [
            Deal(
                buyer_id=buyer.id,
                seller_id=seller.id,
                description=f"paged deal {idx}",
                status=DealStatus.pending_confirmation,
                currency_id=currency.id,
                amount=10 + idx,
                created_at=now - timedelta(minutes=idx),
            )
            for idx in range(4)
        ]
        session.add_all(deals)
        await session.commit()
        expected_ids = [deals[1].id, deals[2].id]

    resp = await client.get(
        "/api/deals",
        params={"limit": 2, "offset": 1},
        headers=auth_headers(init),
    )

    assert resp.status_code == 200, resp.text
    assert int(resp.headers["X-Total-Count"]) == 4
    assert [row["id"] for row in resp.json()] == expected_ids
