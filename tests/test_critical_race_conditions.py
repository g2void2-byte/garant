"""Regression tests for the three Critical findings in the May code review:

* **C1** ``create_withdrawal`` race-condition — two concurrent withdraw
  requests against the same balance must not both succeed when the user
  doesn't have enough funds for both.
* **C2** ``create_deal`` / ``_debit`` race-condition — two concurrent
  deal-creation requests against the same buyer balance must not both
  succeed when the user doesn't have enough funds for both.
* **C3** ``manual_deposit`` 500 — two requests with the same amount must
  not collide on ``provider_invoice_id`` and bubble up an
  ``IntegrityError``.

The fix for C1 and C2 is a ``FOR UPDATE`` row lock on ``UserBalance``;
the fix for C3 is a UUID-suffixed ``provider_invoice_id``.

V5-B-1 / V5-B-2 — two more concurrency fixes covered here:

* webhook → ``services_payments.handle_invoice_paid`` →
  ``services_wallet.credit_deposit`` for the multi-currency
  ``WalletDeposit`` path, and
* webhook → ``services_payments.handle_invoice_paid`` →
  ``services.credit_invoice`` for the legacy ``Invoice`` path.

Both close the same shape of race: two concurrent webhook deliveries
(CryptoBot retry / proxy duplication) read the ``pending`` row,
both pass the status check, both credit. Fix is ``SELECT ... FOR
UPDATE`` on the deposit/invoice row inside ``handle_invoice_paid``
plus a ``FOR UPDATE`` lock on the balance row inside the credit
helper, with a status recheck after each lock so the loser of the
race exits idempotently.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from decimal import Decimal

import pytest
from sqlalchemy import select

from .helpers import auth_headers, credit_balance, get_user_id_by_tg, setup_pin, signed_init_data


def _sign_webhook(body: bytes) -> str:
    """Mirror tests/test_cryptobot_webhook.py::_sign — HMAC-SHA256 of the
    body keyed by SHA-256 of the test CryptoBot token from conftest."""
    secret = "test-cryptobot-token-for-pytest"
    key = hashlib.sha256(secret.encode()).digest()
    return hmac.new(key, body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_concurrent_withdrawals_cannot_overdraw(client):
    """C1 — two parallel withdrawals of >½ balance must not both succeed.

    The user has 100 USDT; two simultaneous 70-USDT withdrawal requests
    arrive. Without the ``FOR UPDATE`` lock both pass the
    ``bal.amount >= amount`` check, both succeed, and the balance ends
    at -40. With the lock one of them sees the post-debit balance and
    fails with 400 ("Недостаточно средств").
    """
    from backend.app.db import async_session
    from backend.app.models import Currency, UserBalance

    init = signed_init_data(7101, "race_withdraw")
    pin_token = await setup_pin(client, init)

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 7101)
        await credit_balance(session, user_id, "USDT", 100.0)

    headers = {**auth_headers(init), "X-Pin-Token": pin_token}
    body = {"currency_code": "USDT", "amount": 70.0, "address": "TXyz123456789abcdef"}

    r1, r2 = await asyncio.gather(
        client.post("/api/wallet/withdrawals", json=body, headers=headers),
        client.post("/api/wallet/withdrawals", json=body, headers=headers),
    )

    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 400], (r1.status_code, r1.text, r2.status_code, r2.text)

    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == user_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        # Spendable balance ends at 30 (= 100 − 70), the other request
        # was rejected. Locked holds the queued withdrawal.
        assert float(bal.amount) == 30.0
        assert float(bal.locked) == 70.0


@pytest.mark.asyncio
async def test_concurrent_deal_creation_cannot_overdraw(client):
    """C2 — two parallel ``create_deal`` requests must not overspend.

    Buyer has 100 USDT; two simultaneous deals of 70 USDT each are
    submitted. Each costs 70 + 5% commission = 73.5 locked. Without the
    ``FOR UPDATE`` lock on ``_debit`` both pass the balance check; with
    the lock one returns 400 ("Недостаточно средств").
    """
    from backend.app.db import async_session
    from backend.app.models import Currency, UserBalance

    buyer_init = signed_init_data(7201, "race_buyer")
    seller_init = signed_init_data(7202, "race_seller")
    buyer_pin = await setup_pin(client, buyer_init)
    await setup_pin(client, seller_init)

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 7201)
        await credit_balance(session, buyer_id, "USDT", 100.0)

    headers = {**auth_headers(buyer_init), "X-Pin-Token": buyer_pin}
    body = {
        "counterparty": "race_seller",
        "role": "buyer",
        "sum": 70.0,
        "description": "race test",
        "pay_comission": "buyer",
        "currency_code": "USDT",
    }

    r1, r2 = await asyncio.gather(
        client.post("/api/deals", json=body, headers=headers),
        client.post("/api/deals", json=body, headers=headers),
    )

    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [201, 400], (r1.status_code, r1.text, r2.status_code, r2.text)

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
        # Only one deal got debited: 100 − 73.5 = 26.5 spendable,
        # 73.5 locked. The balance must never go negative.
        assert float(bal.amount) >= 0
        assert float(bal.amount) == pytest.approx(26.5)
        assert float(bal.locked) == pytest.approx(73.5)


@pytest.mark.asyncio
async def test_manual_deposit_same_amount_does_not_collide(client):
    """C3 — repeated ``POST /api/payments/deposit`` with identical amount
    must not blow up on the ``provider_invoice_id`` UNIQUE constraint.

    Before the fix the row id was ``manual-{user.id}-{amount}``, so two
    requests for the same amount within the rate-limit window raised
    ``IntegrityError`` → 500. The UUID suffix removes the collision.
    """
    init = signed_init_data(7301, "manual_dep")
    await client.get("/api/me", headers=auth_headers(init))

    r1 = await client.post(
        "/api/payments/deposit", json={"amount": 25.0}, headers=auth_headers(init)
    )
    r2 = await client.post(
        "/api/payments/deposit", json={"amount": 25.0}, headers=auth_headers(init)
    )

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r1.json()["id"] != r2.json()["id"]


# ── V5-B-1 / V5-B-2: parallel-webhook double-credit ────────────────────


# How many parallel webhook deliveries we fire to provoke the race.
# Five mirrors the audit's parametrised concurrency suggestion and is
# enough to expose the pre-fix double-credit reliably (2 was already
# enough but ≥5 makes the assertion authoritative).
_WEBHOOK_FANOUT = 5


@pytest.mark.asyncio
async def test_concurrent_invoice_paid_webhook_credits_wallet_only_once(client):
    """V5-B-1 — N parallel ``invoice_paid`` webhook deliveries for the
    SAME pending ``WalletDeposit`` must credit the user balance
    exactly once.

    Pre-fix race: ``handle_invoice_paid`` looked the row up without a
    lock, both deliveries read ``status=pending``, both passed the
    guard, both called ``credit_deposit``, and ``UserBalance.amount``
    was incremented twice. The fix is a ``SELECT ... FOR UPDATE`` on
    the ``WalletDeposit`` row inside ``handle_invoice_paid`` plus a
    ``FOR UPDATE`` lock on the ``UserBalance`` row inside
    ``credit_deposit``; the loser of the race re-reads the row and
    sees ``status=paid`` so it returns idempotently.
    """
    from backend.app.db import async_session
    from backend.app.models import (
        Currency,
        Notification,
        NotificationType,
        UserBalance,
        WalletDeposit,
        WalletDepositStatus,
    )

    init = signed_init_data(7401, "race_webhook_wallet")
    await setup_pin(client, init)

    deposit_amount = Decimal("42.0")
    provider_id = "cb-race-wallet-1"

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 7401)
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        usdt_id = usdt.id
        session.add(
            WalletDeposit(
                user_id=user_id,
                currency_id=usdt_id,
                amount=deposit_amount,
                provider_invoice_id=provider_id,
                pay_url="http://example.com/pay",
                status=WalletDepositStatus.pending,
            )
        )
        await session.commit()

    body = json.dumps(
        {
            "update_type": "invoice_paid",
            "payload": {"invoice_id": provider_id, "status": "paid"},
        }
    ).encode()
    sig = _sign_webhook(body)
    headers = {
        "crypto-pay-api-signature": sig,
        "Content-Type": "application/json",
    }

    # Fire N parallel webhook deliveries against the same pending row.
    # ``asyncio.gather`` produces enough overlap to expose the pre-fix
    # double-credit; the existing C1/C2 tests in this file use the
    # same shape with two requests and reliably catch their races.
    responses = await asyncio.gather(
        *[
            client.post("/api/payments/webhook/cryptobot", content=body, headers=headers)
            for _ in range(_WEBHOOK_FANOUT)
        ]
    )

    # Every delivery returns 200 OK (the loser returns ``already_paid``).
    for resp in responses:
        assert resp.status_code == 200, resp.text
        assert resp.json()["ok"] is True

    # Exactly one delivery actually credited; the other ``_WEBHOOK_FANOUT
    # - 1`` saw ``already_paid`` after re-checking under the row lock.
    credited = [r for r in responses if not r.json().get("already_paid")]
    assert len(credited) == 1, [r.json() for r in responses]

    async with async_session() as session:
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == user_id,
                    UserBalance.currency_id == usdt_id,
                )
            )
        ).scalar_one()
        # Balance equals exactly the deposit amount (NOT N × amount).
        # That's the regression assertion — pre-fix this would be
        # 42 × _WEBHOOK_FANOUT.
        assert Decimal(str(bal.amount)) == deposit_amount

        dep = (
            await session.execute(
                select(WalletDeposit).where(WalletDeposit.provider_invoice_id == provider_id)
            )
        ).scalar_one()
        assert dep.status == WalletDepositStatus.paid

        # Notifier fires once per ``credit_deposit`` invocation; with
        # the fix only one credit happens, so there must be exactly
        # one ``deposits`` notification for this user.
        notifs = (
            (
                await session.execute(
                    select(Notification).where(
                        Notification.recipient_id == user_id,
                        Notification.type == NotificationType.deposits,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(notifs) == 1, [n.title for n in notifs]


@pytest.mark.asyncio
async def test_concurrent_invoice_paid_webhook_credits_legacy_only_once(client):
    """V5-B-2 — N parallel ``invoice_paid`` webhook deliveries for the
    SAME pending legacy ``Invoice`` must credit ``User.balance``
    exactly once.

    Pre-fix race: ``handle_invoice_paid`` looked up the legacy row
    without a lock and ``credit_invoice`` did a plain
    ``session.get(User, ...)`` before mutating ``owner.balance``,
    so two webhook deliveries both passed the ``status=pending`` check
    and both incremented the User.balance column. The fix is a
    ``SELECT ... FOR UPDATE`` on the ``Invoice`` row in
    ``handle_invoice_paid`` plus a ``FOR UPDATE`` lock on the User row
    in ``credit_invoice`` with a refresh-and-recheck of
    ``invoice.status`` immediately after the User lock.
    """
    from backend.app.db import async_session
    from backend.app.models import (
        Invoice,
        InvoiceProvider,
        InvoiceStatus,
        Notification,
        NotificationType,
        User,
    )

    init = signed_init_data(7402, "race_webhook_legacy")
    await setup_pin(client, init)

    invoice_amount = Decimal("99.50")
    provider_id = "cb-race-legacy-1"

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 7402)
        session.add(
            Invoice(
                owner_id=user_id,
                provider=InvoiceProvider.cryptobot,
                provider_invoice_id=provider_id,
                amount=invoice_amount,
                status=InvoiceStatus.pending,
            )
        )
        await session.commit()

    body = json.dumps(
        {
            "update_type": "invoice_paid",
            "payload": {"invoice_id": provider_id, "status": "paid"},
        }
    ).encode()
    sig = _sign_webhook(body)
    headers = {
        "crypto-pay-api-signature": sig,
        "Content-Type": "application/json",
    }

    responses = await asyncio.gather(
        *[
            client.post("/api/payments/webhook/cryptobot", content=body, headers=headers)
            for _ in range(_WEBHOOK_FANOUT)
        ]
    )

    for resp in responses:
        assert resp.status_code == 200, resp.text
        assert resp.json()["ok"] is True

    credited = [r for r in responses if not r.json().get("already_paid")]
    assert len(credited) == 1, [r.json() for r in responses]

    async with async_session() as session:
        owner = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        # ``User.balance`` ends at exactly the invoice amount, NOT
        # N × amount.
        assert Decimal(str(owner.balance)) == invoice_amount

        inv = (
            await session.execute(select(Invoice).where(Invoice.provider_invoice_id == provider_id))
        ).scalar_one()
        assert inv.status == InvoiceStatus.paid

        notifs = (
            (
                await session.execute(
                    select(Notification).where(
                        Notification.recipient_id == user_id,
                        Notification.type == NotificationType.deposits,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(notifs) == 1, [n.title for n in notifs]
