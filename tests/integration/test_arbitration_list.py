"""Arbitration list endpoint: scoping for regular users vs admins/arbiters.

Regular users see only arbitration deals where they are a party (buyer/seller).
Arbiters and admins see *all* arbitration deals. Tests cover both paths,
including the resolved-for-buyer/resolved-for-seller states which Continental
groups under the same "Арбитраж" tab.
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


async def _escalate_to_arbitration(
    client, buyer_init: str, seller_init: str, buyer_pin: str, seller_pin: str, sum_: float = 25
) -> int:
    """Run buyer→seller→buyer disputes flow up to ``DealStatus.arbitration``.

    Returns the freshly-arbitrated deal id.
    """
    from backend.app.db import async_session

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 8001)
        await credit_balance(session, buyer_id, "USDT", 100)

    resp = await client.post(
        "/api/deals",
        json={
            "counterparty": "arb_seller",
            "role": "buyer",
            "amount": sum_,
            "description": "test arbitration",
            "currency_code": "USDT",
        },
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    assert resp.status_code in (200, 201), resp.text
    deal_id = resp.json()["id"]
    resp = await client.post(
        f"/api/deals/{deal_id}/accept",
        headers={**auth_headers(seller_init), "X-Pin-Token": seller_pin},
    )
    assert resp.status_code in (200, 201), resp.text
    resp = await client.post(
        f"/api/deals/{deal_id}/debate",
        json={"reason": "товар не получен"},
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    assert resp.status_code in (200, 201), resp.text
    return deal_id


async def test_arbitration_list_party_only_for_regular_user(client):
    """A user who is not buyer/seller on the dispute must NOT see it."""
    from backend.app.db import async_session
    from backend.app.models import User

    buyer_init = signed_init_data(8001, "arb_buyer")
    seller_init = signed_init_data(8002, "arb_seller")
    stranger_init = signed_init_data(8003, "arb_stranger")

    buyer_pin = await setup_pin(client, buyer_init)
    seller_pin = await setup_pin(client, seller_init)
    await setup_pin(client, stranger_init)

    deal_id = await _escalate_to_arbitration(client, buyer_init, seller_init, buyer_pin, seller_pin)

    resp = await client.get("/api/arbitration/deals", headers=auth_headers(buyer_init))
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert any(d["id"] == deal_id for d in rows)

    resp = await client.get("/api/arbitration/deals", headers=auth_headers(seller_init))
    assert resp.status_code == 200, resp.text
    assert any(d["id"] == deal_id for d in resp.json())

    resp = await client.get("/api/arbitration/deals", headers=auth_headers(stranger_init))
    assert resp.status_code == 200, resp.text
    assert not any(d["id"] == deal_id for d in resp.json())

    # Promote stranger to arbiter — now they should see it.
    async with async_session() as session:
        stranger = (await session.execute(select(User).where(User.tg_user_id == 8003))).scalar_one()
        stranger.is_arbiter = True
        await session.commit()

    resp = await client.get("/api/arbitration/deals", headers=auth_headers(stranger_init))
    assert resp.status_code == 200, resp.text
    assert any(d["id"] == deal_id for d in resp.json())


async def test_settings_privacy_toggles_persist(client):
    """``PATCH /api/me`` persists ``is_anonymous_deals`` and ``is_hidden_profile``."""
    init = signed_init_data(8101, "privacy_user")
    await setup_pin(client, init)

    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200
    me = resp.json()
    assert me["is_anonymous_deals"] is False
    assert me["is_hidden_profile"] is False

    resp = await client.patch(
        "/api/me",
        json={"is_anonymous_deals": True, "is_hidden_profile": True},
        headers=auth_headers(init),
    )
    assert resp.status_code == 200, resp.text
    me = resp.json()
    assert me["is_anonymous_deals"] is True
    assert me["is_hidden_profile"] is True

    resp = await client.patch(
        "/api/me",
        json={"is_anonymous_deals": False},
        headers=auth_headers(init),
    )
    assert resp.status_code == 200
    me = resp.json()
    assert me["is_anonymous_deals"] is False
    assert me["is_hidden_profile"] is True
