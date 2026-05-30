"""End-to-end happy path: create → accept → finish → review."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from tests.helpers import (
    auth_headers,
    credit_balance,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)


async def test_happy_path_deal(client):
    from backend.app.db import async_session
    from backend.app.models import Currency, DealStatus, UserBalance

    buyer_init = signed_init_data(1001, "buyer1")
    seller_init = signed_init_data(1002, "seller1")

    buyer_pin = await setup_pin(client, buyer_init)
    seller_pin = await setup_pin(client, seller_init)

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 1001)
        seller_id = await get_user_id_by_tg(session, 1002)
        await credit_balance(session, buyer_id, "USDT", 100)

    # Buyer creates the deal. P10 — the legacy ``POST /api/deals``
    # path locks only the principal in ``UserBalance.locked``;
    # commission is the deposit-invoice's job (see
    # ``create_deal_with_topup``). Spot-checking that this legacy
    # path still drives the in-progress → completed transition keeps
    # the existing rollback tests green while P10 is the new default.
    create_resp = await client.post(
        "/api/deals",
        json={
            "counterparty": "seller1",
            "role": "buyer",
            "amount": 10,
            "description": "test happy path",
            "currency_code": "USDT",
        },
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    assert create_resp.status_code == 201, create_resp.text
    deal = create_resp.json()
    assert deal["status"] == DealStatus.pending_confirmation.value
    assert deal["currency_code"] == "USDT"
    deal_id = deal["id"]

    # Seller accepts.
    accept_resp = await client.post(
        f"/api/deals/{deal_id}/accept",
        headers={**auth_headers(seller_init), "X-Pin-Token": seller_pin},
    )
    assert accept_resp.status_code == 200, accept_resp.text
    assert accept_resp.json()["status"] == DealStatus.in_progress.value

    # Buyer finishes.
    finish_resp = await client.post(
        f"/api/deals/{deal_id}/finish",
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    assert finish_resp.status_code == 200, finish_resp.text
    assert finish_resp.json()["status"] == DealStatus.completed.value

    # Verify money moved: buyer spent 10 principal + 0.5 commission,
    # seller got the 10 principal.
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        seller_bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == seller_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        assert float(seller_bal.amount) == 10.0
        buyer_bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == buyer_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        # H-02 — the legacy route is now a thin with-topup shim, so
        # a fully-funded buyer pays the same commission as the main flow.
        assert float(buyer_bal.amount) == 89.5  # 100 - 10 - 0.5
        assert float(buyer_bal.locked) == 0.0


async def test_decline_refunds_buyer(client):
    from backend.app.db import async_session
    from backend.app.models import Currency, DealStatus, UserBalance

    buyer_init = signed_init_data(1101, "buyer11")
    seller_init = signed_init_data(1102, "seller11")
    buyer_pin = await setup_pin(client, buyer_init)
    seller_pin = await setup_pin(client, seller_init)

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 1101)
        await credit_balance(session, buyer_id, "USDT", 50)

    create_resp = await client.post(
        "/api/deals",
        json={
            "counterparty": "seller11",
            "role": "buyer",
            "amount": 20,
            "currency_code": "USDT",
        },
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    deal_id = create_resp.json()["id"]

    decline_resp = await client.post(
        f"/api/deals/{deal_id}/decline",
        headers={**auth_headers(seller_init), "X-Pin-Token": seller_pin},
    )
    assert decline_resp.status_code == 200
    assert decline_resp.json()["status"] == DealStatus.cancelled.value

    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        buyer_bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == buyer_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        # H-02 — the legacy route now collects the same commission as
        # ``/with-topup``; decline refunds only the locked principal.
        assert float(buyer_bal.amount) == 49.0
        assert float(buyer_bal.locked) == 0.0


async def test_legacy_create_without_balance_issues_topup_invoice(client, _stub_cryptopay):
    from backend.app.models import DealStatus

    buyer_init = signed_init_data(1201, "buyer12")
    seller_init = signed_init_data(1202, "seller12")
    buyer_pin = await setup_pin(client, buyer_init)
    await setup_pin(client, seller_init)

    # No balance credited — legacy POST /api/deals must no longer reject
    # before commission collection; it returns the same pending_topup deal
    # and inline invoice as /api/deals/with-topup.
    resp = await client.post(
        "/api/deals",
        json={
            "counterparty": "seller12",
            "role": "buyer",
            "amount": 1,
            "currency_code": "USDT",
        },
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == DealStatus.pending_topup.value
    assert body["commission_paid"] is False
    invoice = body["topup_invoice"]
    assert invoice is not None
    assert Decimal(str(invoice["topup_principal"])) == Decimal("1")
    assert Decimal(str(invoice["commission"])) == Decimal("0.05")
    assert Decimal(str(invoice["total"])) == Decimal("1.05")
