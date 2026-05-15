"""Wallet withdrawal endpoint tests.

Verifies that ``POST /api/wallet/withdrawals`` is PIN-gated (since the
endpoint moves money out of escrow and is therefore as sensitive as
the deal-creation/transfer endpoints). Without an ``X-Pin-Token``
header the request must be rejected with 401, regardless of balance.
"""

from __future__ import annotations

import pytest

from .helpers import auth_headers, credit_balance, get_user_id_by_tg, setup_pin, signed_init_data


@pytest.mark.asyncio
async def test_withdrawal_requires_pin_token(client):
    """Missing X-Pin-Token must reject with 401 even with sufficient balance."""
    from backend.app.db import async_session

    init = signed_init_data(7001, "withdraw_user_a")
    await setup_pin(client, init)

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 7001)
        await credit_balance(session, user_id, "USDT", 500.0)

    # V5-B-4 — TRC20 USDT addresses are 34 chars starting with ``T``
    # and matching the base58 alphabet. The test pin-gate runs **before**
    # the address regex check in ``create_withdrawal``, so a placeholder
    # would work here, but mirroring the realistic shape keeps the body
    # consistent with the success-path test below.
    resp = await client.post(
        "/api/wallet/withdrawals",
        json={"currency_code": "USDT", "amount": 50.0, "address": "T" + "x" * 33},
        headers=auth_headers(init),
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_withdrawal_succeeds_with_pin_token(client):
    """Same call with a valid X-Pin-Token must succeed."""
    from backend.app.db import async_session

    init = signed_init_data(7002, "withdraw_user_b")
    pin_token = await setup_pin(client, init)

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 7002)
        await credit_balance(session, user_id, "USDT", 500.0)

    address = "T" + "x" * 33
    resp = await client.post(
        "/api/wallet/withdrawals",
        json={"currency_code": "USDT", "amount": 50.0, "address": address},
        headers={**auth_headers(init), "X-Pin-Token": pin_token},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["amount"] == 50.0
    assert body["status"] == "pending"
    assert body["address"] == address


@pytest.mark.asyncio
async def test_withdrawal_rejects_bogus_pin_token(client):
    """Garbage X-Pin-Token must reject with 401."""
    from backend.app.db import async_session

    init = signed_init_data(7003, "withdraw_user_c")
    await setup_pin(client, init)

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 7003)
        await credit_balance(session, user_id, "USDT", 500.0)

    resp = await client.post(
        "/api/wallet/withdrawals",
        json={"currency_code": "USDT", "amount": 50.0, "address": "T" + "x" * 33},
        headers={**auth_headers(init), "X-Pin-Token": "not-a-real-token"},
    )
    assert resp.status_code == 401, resp.text
