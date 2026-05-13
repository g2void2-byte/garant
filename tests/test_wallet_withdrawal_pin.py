"""Verify ``POST /api/wallet/withdrawals`` is PIN-gated.

Regression guard for the P0 finding from the previous session — the
endpoint used to depend on ``CurrentUser`` instead of ``PinUser``, so any
authenticated user could drain their wallet balance without re-entering
the PIN. Each case below exercises one branch of ``require_pin_session``.
"""

from __future__ import annotations

from tests.helpers import (
    auth_headers,
    credit_balance,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)


async def test_withdraw_without_pin_setup_is_403(client):
    """A user who never set a PIN must get 403, not 200."""
    init = signed_init_data(4001, "no_pin_user")
    # Create the user row by hitting any CurrentUser endpoint.
    me = await client.get("/api/me", headers=auth_headers(init))
    assert me.status_code == 200, me.text

    resp = await client.post(
        "/api/wallet/withdrawals",
        json={"currency_code": "USDT", "amount": 5, "address": "TXYZ" + "0" * 30},
        headers=auth_headers(init),
    )
    assert resp.status_code == 403, resp.text
    assert "PIN" in resp.json()["detail"]


async def test_withdraw_without_pin_token_is_401(client):
    """User has a PIN but didn't pass X-Pin-Token → 401."""
    init = signed_init_data(4002, "no_token_user")
    await setup_pin(client, init)

    resp = await client.post(
        "/api/wallet/withdrawals",
        json={"currency_code": "USDT", "amount": 5, "address": "TXYZ" + "0" * 30},
        headers=auth_headers(init),
    )
    assert resp.status_code == 401, resp.text


async def test_withdraw_with_bad_pin_token_is_401(client):
    """Malformed or wrong-signed PIN token → 401, no balance touched."""
    init = signed_init_data(4003, "bad_token_user")
    await setup_pin(client, init)

    resp = await client.post(
        "/api/wallet/withdrawals",
        json={"currency_code": "USDT", "amount": 5, "address": "TXYZ" + "0" * 30},
        headers={**auth_headers(init), "X-Pin-Token": "not-a-real-token"},
    )
    assert resp.status_code == 401, resp.text


async def test_withdraw_with_pin_token_succeeds(client):
    """Sanity check: with a valid PIN session the request reaches the
    business logic and creates a pending withdrawal."""
    from backend.app.db import async_session

    init = signed_init_data(4004, "good_pin_user")
    pin_token = await setup_pin(client, init)

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 4004)
        await credit_balance(session, user_id, "USDT", 50)

    resp = await client.post(
        "/api/wallet/withdrawals",
        json={"currency_code": "USDT", "amount": 10, "address": "TXYZ" + "0" * 30},
        headers={**auth_headers(init), "X-Pin-Token": pin_token},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["amount"] == 10
    assert body["currency"]["code"] == "USDT"
