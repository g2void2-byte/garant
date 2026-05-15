"""PIN-gate for POST /api/wallet/withdrawals.

Regression for the §4.1 finding from the previous session: the new
multi-currency withdrawal endpoint depended on ``CurrentUser`` instead
of ``PinUser`` and was therefore reachable without a PIN session — same
hole that was closed for the legacy ``/api/payments/withdraw`` in #22.
"""

from __future__ import annotations

from backend.app.db import async_session
from tests.helpers import (
    auth_headers,
    credit_balance,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)


async def test_withdrawal_requires_pin_session(client):
    """Without ``X-Pin-Token`` the endpoint must reject with 401."""
    init = signed_init_data(4001, "wd_no_pin")
    await setup_pin(client, init, pin="3741")

    async with async_session() as session:
        uid = await get_user_id_by_tg(session, 4001)
        await credit_balance(session, uid, "USDT", 100.0)

    resp = await client.post(
        "/api/wallet/withdrawals",
        json={"currency_code": "USDT", "amount": 10.0, "address": "T" + "x" * 33},
        headers=auth_headers(init),
    )
    assert resp.status_code == 401, resp.text


async def test_withdrawal_rejects_invalid_pin_token(client):
    init = signed_init_data(4002, "wd_bad_pin")
    await setup_pin(client, init, pin="3741")

    async with async_session() as session:
        uid = await get_user_id_by_tg(session, 4002)
        await credit_balance(session, uid, "USDT", 100.0)

    resp = await client.post(
        "/api/wallet/withdrawals",
        json={"currency_code": "USDT", "amount": 10.0, "address": "T" + "x" * 33},
        headers={**auth_headers(init), "X-Pin-Token": "not-a-real-token"},
    )
    assert resp.status_code == 401, resp.text


async def test_withdrawal_succeeds_with_valid_pin_session(client):
    init = signed_init_data(4003, "wd_ok")
    pin_token = await setup_pin(client, init, pin="3741")

    async with async_session() as session:
        uid = await get_user_id_by_tg(session, 4003)
        await credit_balance(session, uid, "USDT", 100.0)

    resp = await client.post(
        "/api/wallet/withdrawals",
        json={"currency_code": "USDT", "amount": 10.0, "address": "T" + "x" * 33},
        headers={**auth_headers(init), "X-Pin-Token": pin_token},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["amount"] == 10.0
    assert body["currency"]["code"] == "USDT"
    assert body["status"] == "pending"
