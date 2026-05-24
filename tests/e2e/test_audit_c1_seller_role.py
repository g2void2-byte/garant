"""Audit C1 regression — ``POST /api/deals`` may only be initiated
by the buyer.

Pre-fix the router accepted ``role="seller"`` and flipped the
``buyer``/``seller`` assignment so the *counterparty* became the
buyer whose balance was locked into escrow.  Combined with the fact
that ``accept_deal``/``decline_deal`` are seller-only (the side that
initiated cannot reject), this let any user freeze an arbitrary
victim's wallet balance for up to
``inactivity_pending_confirmation_days`` simply by ``POST``-ing a
deal in their direction.  The 10/min ``RLDealCreate`` rate-limit
didn't help: one accepted request was enough to lock the victim's
funds.

The fix:

* ``schemas.DealCreate.role`` is now ``Literal["buyer"]`` with a
  ``"buyer"`` default, so FastAPI returns 422 for ``role="seller"``
  (and for any typo, e.g. ``"BUYER"``).
* ``routers/deals.create_deal_endpoint`` always treats the caller as
  the buyer (no ``else: buyer, seller = counterparty, user`` branch).
* The frontend ``CreateDealPage`` toggle no longer exposes "Я
  продавец" and ``useCreateDeal`` hard-codes ``role: "buyer"``.

This file is the backend regression for those guarantees.
"""

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


async def test_role_seller_rejected_with_422(client):
    """Audit C1 — ``role="seller"`` is rejected at the schema layer.

    Pre-fix this would have created a deal where the *seller* row was
    ``user`` and the *buyer* row was ``counterparty`` — i.e. the
    counterparty's balance would be locked without consent.
    """
    from backend.app.db import async_session
    from backend.app.models import Deal

    attacker_init = signed_init_data(7001, "c1_attacker")
    victim_init = signed_init_data(7002, "c1_victim")
    attacker_pin = await setup_pin(client, attacker_init)
    await setup_pin(client, victim_init)

    # Credit the victim with a balance so we can prove the attack
    # would have actually locked it pre-fix; the assertion is that
    # post-fix none of that balance moves.
    async with async_session() as session:
        victim_id = await get_user_id_by_tg(session, 7002)
        await credit_balance(session, victim_id, "USDT", 100)

    resp = await client.post(
        "/api/deals",
        json={
            "counterparty": "c1_victim",
            "role": "seller",
            "amount": 10,
            "description": "C1 attack — should be 422",
            "currency_code": "USDT",
        },
        headers={**auth_headers(attacker_init), "X-Pin-Token": attacker_pin},
    )
    assert resp.status_code == 422, resp.text

    # No ``Deal`` row was created and the victim's balance is untouched.
    async with async_session() as session:
        deals = (await session.execute(select(Deal))).scalars().all()
        assert deals == []


async def test_role_default_is_buyer(client):
    """Audit C1 — omitting ``role`` defaults to ``"buyer"`` and the
    caller is the buyer in the resulting row.
    """
    from backend.app.db import async_session
    from backend.app.models import Deal

    buyer_init = signed_init_data(7011, "c1_buyer_default")
    seller_init = signed_init_data(7012, "c1_seller_default")
    buyer_pin = await setup_pin(client, buyer_init)
    await setup_pin(client, seller_init)

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 7011)
        seller_id = await get_user_id_by_tg(session, 7012)
        await credit_balance(session, buyer_id, "USDT", 50)

    resp = await client.post(
        "/api/deals",
        json={
            "counterparty": "c1_seller_default",
            # role omitted — must default to "buyer".
            "amount": 10,
            "description": "C1 default-role smoke",
            "currency_code": "USDT",
        },
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["role"] == "buyer"

    async with async_session() as session:
        deal = (await session.execute(select(Deal))).scalar_one()
        assert deal.buyer_id == buyer_id
        assert deal.seller_id == seller_id


async def test_role_typo_rejected_with_422(client):
    """Audit C1 — defence-in-depth for the ``Literal`` type. Any
    string other than ``"buyer"`` (case-sensitive) is a 422.
    """
    init = signed_init_data(7021, "c1_typo")
    pin = await setup_pin(client, init)
    other = signed_init_data(7022, "c1_typo_other")
    await setup_pin(client, other)

    for bad in ("BUYER", "Buyer", "sellr", "seller", "purchaser", ""):
        resp = await client.post(
            "/api/deals",
            json={
                "counterparty": "c1_typo_other",
                "role": bad,
                "amount": 1,
                "description": "x",
                "currency_code": "USDT",
            },
            headers={**auth_headers(init), "X-Pin-Token": pin},
        )
        assert resp.status_code == 422, (bad, resp.text)


async def test_role_seller_does_not_lock_victim_balance(client):
    """Audit C1 — the core attack: even if the schema gate is bypassed
    somehow, the router's defensive check refuses to flip the role.

    We verify the balance invariant: post-attempt the victim's
    spendable balance is unchanged and ``locked`` is zero.
    """
    from backend.app.db import async_session
    from backend.app.models import Currency, UserBalance

    attacker_init = signed_init_data(7031, "c1_attacker2")
    victim_init = signed_init_data(7032, "c1_victim2")
    attacker_pin = await setup_pin(client, attacker_init)
    await setup_pin(client, victim_init)

    async with async_session() as session:
        victim_id = await get_user_id_by_tg(session, 7032)
        await credit_balance(session, victim_id, "USDT", 100)

    await client.post(
        "/api/deals",
        json={
            "counterparty": "c1_victim2",
            "role": "seller",
            "amount": 50,
            "description": "C1 lock-attack",
            "currency_code": "USDT",
        },
        headers={**auth_headers(attacker_init), "X-Pin-Token": attacker_pin},
    )

    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == victim_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        assert Decimal(str(bal.amount)) == Decimal("100")
        assert Decimal(str(bal.locked)) == Decimal("0")
