"""Arbitration flow: escalate from in_progress → arbiter resolves."""

from __future__ import annotations

from sqlalchemy import select

from tests.helpers import (
    auth_headers,
    credit_balance,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)


async def test_arbitration_resolved_for_buyer_refunds(client):
    from backend.app.db import async_session
    from backend.app.models import Currency, DealStatus, User, UserBalance

    buyer_init = signed_init_data(2001, "buyer2")
    seller_init = signed_init_data(2002, "seller2")
    admin_init = signed_init_data(2003, "admin2")

    buyer_pin = await setup_pin(client, buyer_init)
    seller_pin = await setup_pin(client, seller_init)
    admin_pin = await setup_pin(client, admin_init)

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 2001)
        admin = (await session.execute(select(User).where(User.tg_user_id == 2003))).scalar_one()
        admin.is_admin = True
        await session.commit()
        await credit_balance(session, buyer_id, "USDT", 100)

    # Create and accept.
    deal_id = (
        await client.post(
            "/api/deals",
            json={
                "counterparty": "seller2",
                "role": "buyer",
                "amount": 20,
                "currency_code": "USDT",
            },
            headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
        )
    ).json()["id"]
    await client.post(
        f"/api/deals/{deal_id}/accept",
        headers={**auth_headers(seller_init), "X-Pin-Token": seller_pin},
    )

    # Buyer escalates to arbitration.
    debate_resp = await client.post(
        f"/api/deals/{deal_id}/debate",
        json={"reason": "Seller ghosted"},
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    assert debate_resp.status_code == 200, debate_resp.text
    assert debate_resp.json()["status"] == DealStatus.arbitration.value

    # Admin resolves for the buyer.
    resolve_resp = await client.post(
        f"/api/deals/{deal_id}/resolve",
        json={"winner": "buyer", "note": "Seller unresponsive"},
        headers={**auth_headers(admin_init), "X-Pin-Token": admin_pin},
    )
    assert resolve_resp.status_code == 200, resolve_resp.text
    assert resolve_resp.json()["status"] == DealStatus.resolved_for_buyer.value

    # Buyer refunded the 20 principal 1:1. P10 — the legacy
    # ``create_deal`` path never locks commission in ``UserBalance``
    # (commission rides on the deposit invoice via
    # ``create_deal_with_topup``), so the refund returns the full
    # principal and the buyer ends at their pre-deal balance.
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
        assert float(bal.amount) == 100.0
        assert float(bal.locked) == 0.0


async def test_arbitration_resolution_bumps_winner_and_loser_counters(client):
    """``resolve_arbitration`` must bump ``deals_success`` on the
    winning side and ``deals_failed`` on the losing side. Per spec,
    voluntary cancellation does NOT touch either counter — only an
    adversarial arbitration outcome does.

    We start each user from a known counter baseline (seller has
    already completed a deal in the buyer-wins resolve so we can also
    assert that the counter doesn't reset)."""
    from backend.app.db import async_session
    from backend.app.models import DealStatus, User

    buyer_init = signed_init_data(2401, "buyerc")
    seller_init = signed_init_data(2402, "sellerc")
    admin_init = signed_init_data(2403, "adminc")

    buyer_pin = await setup_pin(client, buyer_init)
    seller_pin = await setup_pin(client, seller_init)
    admin_pin = await setup_pin(client, admin_init)

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 2401)
        seller_id = await get_user_id_by_tg(session, 2402)
        admin = (await session.execute(select(User).where(User.tg_user_id == 2403))).scalar_one()
        admin.is_admin = True
        # Pre-seed seller with a stale counter so we know the bump is
        # additive, not an absolute assignment.
        seller = await session.get(User, seller_id)
        assert seller is not None
        seller.deals_failed = 7
        await session.commit()
        await credit_balance(session, buyer_id, "USDT", 100)

    deal_id = (
        await client.post(
            "/api/deals",
            json={
                "counterparty": "sellerc",
                "role": "buyer",
                "amount": 20,
                "currency_code": "USDT",
            },
            headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
        )
    ).json()["id"]
    await client.post(
        f"/api/deals/{deal_id}/accept",
        headers={**auth_headers(seller_init), "X-Pin-Token": seller_pin},
    )
    await client.post(
        f"/api/deals/{deal_id}/debate",
        json={"reason": "no delivery"},
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    resp = await client.post(
        f"/api/deals/{deal_id}/resolve",
        json={"winner": "buyer", "note": "buyer wins"},
        headers={**auth_headers(admin_init), "X-Pin-Token": admin_pin},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == DealStatus.resolved_for_buyer.value

    async with async_session() as session:
        buyer = await session.get(User, buyer_id)
        seller = await session.get(User, seller_id)
        assert buyer is not None and seller is not None
        # Winner gets a single ``deals_success`` bump from
        # ``resolve_arbitration``; nothing in the flow above touches
        # the success counter for the buyer.
        assert buyer.deals_success == 1, buyer.deals_success
        assert buyer.deals_failed == 0
        # Seller's pre-seeded counter was 7 — the arbitration loss
        # added exactly one more, proving the UPDATE is additive
        # rather than an absolute assignment.
        assert seller.deals_failed == 8, seller.deals_failed
        assert seller.deals_success == 0, seller.deals_success


async def test_resolve_requires_admin_or_arbiter(client):
    from backend.app.db import async_session

    buyer_init = signed_init_data(2101, "buyer21")
    seller_init = signed_init_data(2102, "seller21")
    rando_init = signed_init_data(2103, "rando21")

    buyer_pin = await setup_pin(client, buyer_init)
    seller_pin = await setup_pin(client, seller_init)
    rando_pin = await setup_pin(client, rando_init)

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 2101)
        await credit_balance(session, buyer_id, "USDT", 50)

    deal_id = (
        await client.post(
            "/api/deals",
            json={
                "counterparty": "seller21",
                "role": "buyer",
                "amount": 10,
                "currency_code": "USDT",
            },
            headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
        )
    ).json()["id"]
    await client.post(
        f"/api/deals/{deal_id}/accept",
        headers={**auth_headers(seller_init), "X-Pin-Token": seller_pin},
    )
    await client.post(
        f"/api/deals/{deal_id}/debate",
        json={"reason": "dispute"},
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )

    # A random non-admin user trying to resolve → 403.
    resp = await client.post(
        f"/api/deals/{deal_id}/resolve",
        json={"winner": "buyer"},
        headers={**auth_headers(rando_init), "X-Pin-Token": rando_pin},
    )
    assert resp.status_code == 403
    assert "запрещён" in resp.json()["detail"].lower()
