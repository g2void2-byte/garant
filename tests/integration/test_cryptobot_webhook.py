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
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
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
        {
            "update_type": "invoice_paid",
            # Audit L-9 — ``handle_invoice_paid`` now compares
            # ``payload["amount"]`` against ``wallet.amount`` before
            # crediting; the real Crypto Pay webhook always emits
            # ``amount`` so we mirror that shape here too.
            "payload": {"invoice_id": "cb-789", "status": "paid", "amount": "42.0"},
        }
    ).encode()
    sig = _sign(body)
    headers = {
        "crypto-pay-api-signature": sig,
        "Content-Type": "application/json",
    }

    # First call credits.
    resp = await client.post("/api/payments/webhook/cryptobot", content=body, headers=headers)
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
    resp2 = await client.post("/api/payments/webhook/cryptobot", content=body, headers=headers)
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
    body = json.dumps({"update_type": "invoice_paid", "payload": {"invoice_id": "x"}}).encode()
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


async def _seed_pending_deposit(tg: int, *, provider_id: str) -> tuple[int, int]:
    """Seed a pending wallet deposit and return ``(user_id, deposit_row_id)``."""
    from backend.app.db import async_session
    from backend.app.models import Currency, WalletDeposit, WalletDepositStatus

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, tg)
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        dep = WalletDeposit(
            user_id=user_id,
            currency_id=usdt.id,
            amount=15.0,
            provider_invoice_id=provider_id,
            pay_url="http://example.com/pay",
            status=WalletDepositStatus.pending,
        )
        session.add(dep)
        await session.commit()
        await session.refresh(dep)
        return user_id, dep.id


async def test_webhook_invoice_expired_marks_pending_deposit_expired(client):
    """I-3 \u2014 a Crypto Pay ``invoice_expired`` webhook for a known
    pending deposit must flip the row to ``expired`` and credit
    nothing. This is the explicit terminal-state path complementing
    the M-6 background sweep."""
    from backend.app.db import async_session
    from backend.app.models import (
        UserBalance,
        WalletDeposit,
        WalletDepositStatus,
    )

    init_data = signed_init_data(3101, "alice101")
    await setup_pin(client, init_data)
    user_id, dep_id = await _seed_pending_deposit(3101, provider_id="cb-exp-1")

    body = json.dumps(
        {
            "update_type": "invoice_expired",
            "payload": {"invoice_id": "cb-exp-1", "status": "expired"},
        }
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
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["ok"] is True
    assert payload.get("expired") is True

    async with async_session() as session:
        row = (
            await session.execute(select(WalletDeposit).where(WalletDeposit.id == dep_id))
        ).scalar_one()
        assert row.status == WalletDepositStatus.expired
        # No UserBalance row at all is fine \u2014 we never credited.
        bal = (
            (await session.execute(select(UserBalance).where(UserBalance.user_id == user_id)))
            .scalars()
            .all()
        )
        assert all(float(b.amount) == 0.0 for b in bal)


async def test_webhook_invoice_expired_via_paid_channel_marks_expired(client):
    """If Crypto Pay sends ``update_type=invoice_paid`` with
    ``payload.status=\"expired\"`` (their funnel does this for some
    invoice types), the router should still terminal-state the row
    via the expired handler instead of trying to credit."""
    from backend.app.db import async_session
    from backend.app.models import WalletDeposit, WalletDepositStatus

    init_data = signed_init_data(3102, "alice102")
    await setup_pin(client, init_data)
    _, dep_id = await _seed_pending_deposit(3102, provider_id="cb-exp-2")

    body = json.dumps(
        {
            "update_type": "invoice_paid",
            "payload": {"invoice_id": "cb-exp-2", "status": "expired"},
        }
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
    assert resp.json().get("expired") is True

    async with async_session() as session:
        row = (
            await session.execute(select(WalletDeposit).where(WalletDeposit.id == dep_id))
        ).scalar_one()
        assert row.status == WalletDepositStatus.expired


async def test_webhook_invoice_expired_is_idempotent_after_paid(client):
    """Once a deposit is ``paid`` a stale expired webhook must NOT
    de-credit the user; the handler returns ``already_terminal``."""
    from backend.app.db import async_session
    from backend.app.models import (
        UserBalance,
        WalletDeposit,
        WalletDepositStatus,
    )

    init_data = signed_init_data(3103, "alice103")
    await setup_pin(client, init_data)
    user_id, dep_id = await _seed_pending_deposit(3103, provider_id="cb-exp-3")

    # First: credit it normally.
    paid_body = json.dumps(
        {
            "update_type": "invoice_paid",
            # Audit L-9 — mirror the real Crypto Pay payload shape so
            # the amount-mismatch check in ``handle_invoice_paid``
            # doesn't refuse the credit.
            "payload": {"invoice_id": "cb-exp-3", "status": "paid", "amount": "42.0"},
        }
    ).encode()
    sig = _sign(paid_body)
    resp = await client.post(
        "/api/payments/webhook/cryptobot",
        content=paid_body,
        headers={
            "crypto-pay-api-signature": sig,
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200

    # Then: a stale expired webhook arrives. It must be a no-op.
    expired_body = json.dumps(
        {
            "update_type": "invoice_expired",
            "payload": {"invoice_id": "cb-exp-3", "status": "expired"},
        }
    ).encode()
    sig2 = _sign(expired_body)
    resp2 = await client.post(
        "/api/payments/webhook/cryptobot",
        content=expired_body,
        headers={
            "crypto-pay-api-signature": sig2,
            "Content-Type": "application/json",
        },
    )
    assert resp2.status_code == 200
    payload = resp2.json()
    assert payload.get("already_terminal") is True

    async with async_session() as session:
        row = (
            await session.execute(select(WalletDeposit).where(WalletDeposit.id == dep_id))
        ).scalar_one()
        assert row.status == WalletDepositStatus.paid
        bal = (
            await session.execute(select(UserBalance).where(UserBalance.user_id == user_id))
        ).scalar_one()
        assert float(bal.amount) == 15.0
