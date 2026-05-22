"""End-to-end happy path: create → accept → finish → review."""

from __future__ import annotations

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

    # Buyer creates the deal — buyer pays commission, so locked = amount + 5%.
    create_resp = await client.post(
        "/api/deals",
        json={
            "counterparty": "seller1",
            "role": "buyer",
            "amount": 10,
            "description": "test happy path",
            "pay_comission": "buyer",
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

    # Verify money moved: buyer spent 10.5, seller got 10.
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
        assert float(buyer_bal.amount) == 89.5  # 100 - 10 - 0.5 commission
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
            "pay_comission": "buyer",
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
        # Commission (5% of 20 = 1) is retained even on decline per spec;
        # buyer gets back only the 20 principal => 30 + 20 = 50, but the 1
        # commission stays on the platform, so final spendable = 49.
        assert float(buyer_bal.amount) == 49.0
        assert float(buyer_bal.locked) == 0.0


async def test_insufficient_balance_rejected(client):
    buyer_init = signed_init_data(1201, "buyer12")
    seller_init = signed_init_data(1202, "seller12")
    buyer_pin = await setup_pin(client, buyer_init)
    await setup_pin(client, seller_init)

    # No balance credited — should reject.
    resp = await client.post(
        "/api/deals",
        json={
            "counterparty": "seller12",
            "role": "buyer",
            "amount": 1,
            "currency_code": "USDT",
            "pay_comission": "buyer",
        },
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    # Item 18 — ``detail`` is now a structured payload so the frontend
    # can render a precise "не хватает X" hint.
    assert detail["code"] == "insufficient_funds"
    assert "Недостаточно" in detail["message"]
    assert detail["currency_code"] == "USDT"
    # Required = amount (1) + 5% commission = 1.05 when buyer pays;
    # balance is 0 so deficit equals required.
    assert float(detail["required"]) == 1.05
    assert float(detail["balance"]) == 0.0
    assert float(detail["deficit"]) == 1.05
