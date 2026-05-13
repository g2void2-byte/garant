"""CryptoBot webhook signature verification + idempotent credit."""

from __future__ import annotations

import hashlib
import hmac
import json

from sqlalchemy import select

from tests.helpers import (
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)


def _sign(body: bytes) -> str:
    secret = "test-cryptobot-token-for-pytest"
    key = hashlib.sha256(secret.encode()).digest()
    return hmac.new(key, body, hashlib.sha256).hexdigest()


async def test_webhook_credits_pending_deposit_and_is_idempotent(client):
    from backend.app.db import async_session
    from backend.app.models import (
        Currency,
        UserBalance,
        WalletDeposit,
        WalletDepositStatus,
    )

    init_data = signed_init_data(3001, "alice3")
    await setup_pin(client, init_data)

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 3001)
        usdt = (
            await session.execute(select(Currency).where(Currency.code == "USDT"))
        ).scalar_one()
        usdt_id = usdt.id
        session.add(
            WalletDeposit(
                user_id=user_id,
                currency_id=usdt_id,
                amount=42.0,
                provider_invoice_id="cb-789",
                pay_url="http://example.com/pay",
                status=WalletDepositStatus.pending,
            )
        )
        await session.commit()

    body = json.dumps(
        {"update_type": "invoice_paid", "payload": {"invoice_id": "cb-789"}}
    ).encode()
    sig = _sign(body)
    headers = {
        "crypto-pay-api-signature": sig,
        "Content-Type": "application/json",
    }

    # First call credits.
    resp = await client.post(
        "/api/payments/webhook/cryptobot", content=body, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True

    async with async_session() as session:
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == user_id,
                    UserBalance.currency_id == usdt_id,
                )
            )
        ).scalar_one()
        assert float(bal.amount) == 42.0

    # Second call: idempotent — no double credit, ``already_paid`` echoed.
    resp2 = await client.post(
        "/api/payments/webhook/cryptobot", content=body, headers=headers
    )
    assert resp2.status_code == 200
    payload = resp2.json()
    assert payload["ok"] is True
    assert payload.get("already_paid") is True

    async with async_session() as session:
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == user_id,
                    UserBalance.currency_id == usdt_id,
                )
            )
        ).scalar_one()
        assert float(bal.amount) == 42.0


async def test_webhook_bad_signature_rejected(client):
    body = json.dumps(
        {"update_type": "invoice_paid", "payload": {"invoice_id": "x"}}
    ).encode()
    resp = await client.post(
        "/api/payments/webhook/cryptobot",
        content=body,
        headers={
            "crypto-pay-api-signature": "deadbeefdeadbeef",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 401


async def test_webhook_unknown_invoice_id_returns_ok_with_reason(client):
    body = json.dumps(
        {"update_type": "invoice_paid", "payload": {"invoice_id": "does-not-exist"}}
    ).encode()
    sig = _sign(body)
    resp = await client.post(
        "/api/payments/webhook/cryptobot",
        content=body,
        headers={
            "crypto-pay-api-signature": sig,
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
