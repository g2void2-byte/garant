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
    body = {"currency_code": "USDT", "amount": 70.0, "address": "T" + "x" * 33}

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


# ── V5-B-1 / V5-B-2 follow-up: webhook vs polling-fallback locking ─────


@pytest.mark.asyncio
async def test_concurrent_webhook_and_poll_credits_wallet_only_once(client, monkeypatch):
    """V5-B-1 follow-up — webhook + polling fallback for the SAME
    pending ``WalletDeposit`` must credit the user balance exactly
    once.

    This exercises the cross-path locking introduced as a follow-up to
    V5-B-1: ``handle_invoice_paid`` already takes ``WalletDeposit FOR
    UPDATE`` and ``poll_deposit_status`` now does the same before
    delegating to ``credit_deposit``, so both entry points acquire
    locks in the order ``WalletDeposit -> UserBalance``. Pre-fix the
    polling path took ``UserBalance FOR UPDATE`` first inside
    ``credit_deposit`` and only updated the unlocked
    ``WalletDeposit`` row at commit, forming a cycle Postgres resolved
    by aborting one transaction.

    The test drives ``poll_deposit_status`` directly at the service
    layer in a fresh ``async_session()`` in parallel with
    ``handle_invoice_paid`` from another session, instead of going
    through ``GET /api/wallet/deposits/{id}``. That avoids having to
    mock the CryptoBot HTTP client globally for the duration of an
    HTTPX/ASGI request — we only need to patch the in-process
    ``CryptoPay`` symbol that ``poll_deposit_status`` resolves so the
    polling side returns a fake ``paid`` invoice. The race shape
    (concurrent webhook + poll on the same row) is the same.
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
    from backend.app.services_payments import handle_invoice_paid
    from backend.app.services_wallet import poll_deposit_status

    init = signed_init_data(7501, "race_webhook_poll_wallet")
    await setup_pin(client, init)

    deposit_amount = Decimal("33.0")
    # ``poll_deposit_status`` coerces ``provider_invoice_id`` to ``int``
    # for the CryptoBot ``get_invoices`` API (real invoice IDs are
    # numeric), so use a numeric-string here. Pre-fix this row used
    # ``"cb-race-webhook-poll-wallet-1"`` and the polling branch
    # crashed with ``ValueError`` before either path could write,
    # making the test flake on whichever task got scheduled first.
    provider_id = "780011001"

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 7501)
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

    # Stub CryptoPay so ``poll_deposit_status`` returns a fake ``paid``
    # invoice without hitting the network. ``poll_deposit_status``
    # imports CryptoPay from ``.cryptopay``; we patch the name where
    # it's resolved (``services_wallet.CryptoPay``).
    class _FakeInvoice:
        status = "paid"

    class _FakeCryptoPay:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def get_invoices(self, *, invoice_ids):  # noqa: ARG002
            return [_FakeInvoice()]

    import backend.app.services_wallet as services_wallet

    monkeypatch.setattr(services_wallet, "CryptoPay", _FakeCryptoPay)

    payload = {"invoice_id": provider_id, "status": "paid"}

    async def _run_webhook():
        async with async_session() as s:
            return await handle_invoice_paid(s, payload)

    async def _run_poll():
        async with async_session() as s:
            dep = (
                await s.execute(
                    select(WalletDeposit).where(WalletDeposit.provider_invoice_id == provider_id)
                )
            ).scalar_one()
            return await poll_deposit_status(s, dep)

    webhook_result, _poll_result = await asyncio.gather(_run_webhook(), _run_poll())

    assert webhook_result.get("ok") is True

    async with async_session() as session:
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == user_id,
                    UserBalance.currency_id == usdt_id,
                )
            )
        ).scalar_one()
        # Exactly the deposit amount (NOT 2x). Pre-fix would credit
        # twice: ``2 * deposit_amount`` or, with the partial fix,
        # one transaction would deadlock-abort.
        assert Decimal(str(bal.amount)) == deposit_amount

        dep = (
            await session.execute(
                select(WalletDeposit).where(WalletDeposit.provider_invoice_id == provider_id)
            )
        ).scalar_one()
        assert dep.status == WalletDepositStatus.paid

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
async def test_concurrent_webhook_and_poll_credits_legacy_only_once(client, monkeypatch):
    """V5-B-2 follow-up — webhook + polling fallback for the SAME
    pending legacy ``Invoice`` must credit ``User.balance`` exactly
    once.

    Same shape as the wallet test above for the legacy
    ``credit_invoice`` path. The polling endpoint
    (``GET /api/payments/deposit/invoice/{id}``) reloads the
    ``Invoice`` row with ``FOR UPDATE`` before calling
    ``credit_invoice``, matching the lock order the webhook
    (``handle_invoice_paid``) uses: Invoice -> User. Pre-fix the poll
    path took the User lock first inside ``credit_invoice`` and only
    updated the unlocked Invoice at commit, forming a cycle.

    Drives the polling fallback through the real router via
    ``GET /api/payments/deposit/invoice/{id}`` with CryptoPay
    monkeypatched on ``backend.app.routers.payments.CryptoPay`` (the
    name resolved by ``from ..cryptopay import CryptoPay`` at the
    router's module load — patching the source module would not
    intercept that already-bound reference). The webhook side runs
    ``handle_invoice_paid`` directly in a parallel session, the same
    pattern the wallet test uses.
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
    from backend.app.services_payments import handle_invoice_paid

    init = signed_init_data(7502, "race_webhook_poll_legacy")
    await setup_pin(client, init)

    invoice_amount = Decimal("57.25")
    # ``check_invoice`` (legacy poll path) coerces the stored
    # ``provider_invoice_id`` via ``int(...)`` before calling the
    # CryptoBot ``get_invoices`` API — real invoice IDs are numeric.
    # Using a ``"cb-…"`` placeholder (matching the wallet sibling
    # fixture) raced against the webhook arm of the test depending on
    # task ordering and caused ``ValueError`` ~40% of the time. Mirror
    # the numeric fix that the wallet test already applies.
    provider_id = "780011001"

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 7502)
        inv = Invoice(
            owner_id=user_id,
            provider=InvoiceProvider.cryptobot,
            provider_invoice_id=provider_id,
            amount=invoice_amount,
            status=InvoiceStatus.pending,
        )
        session.add(inv)
        await session.commit()
        await session.refresh(inv)
        invoice_id = inv.id

    # Stub CryptoPay so the polling endpoint
    # ``GET /api/payments/deposit/invoice/{id}`` returns a fake
    # ``paid`` invoice without hitting the network. ``check_invoice``
    # imports CryptoPay via ``from ..cryptopay import CryptoPay``, so
    # the symbol to patch is the one bound on ``routers.payments``,
    # not the source module — patching the source module would leave
    # the already-resolved router-side reference untouched.
    class _FakeInvoice:
        status = "paid"

    class _FakeCryptoPay:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def get_invoices(self, *, invoice_ids):  # noqa: ARG002
            return [_FakeInvoice()]

    import backend.app.routers.payments as payments_router

    monkeypatch.setattr(payments_router, "CryptoPay", _FakeCryptoPay)

    payload = {"invoice_id": provider_id, "status": "paid"}

    async def _run_webhook():
        async with async_session() as s:
            return await handle_invoice_paid(s, payload)

    async def _run_poll():
        # Drive the real router so the V5-B-2 follow-up's
        # ``select(Invoice).with_for_update()`` reload inside
        # ``check_invoice`` is exercised. A future regression that
        # drops the FOR UPDATE reload (or moves it outside the
        # ``checks[0].status == "paid"`` branch) would surface as a
        # double-credit / deadlock here.
        return await client.get(
            f"/api/payments/deposit/invoice/{invoice_id}",
            headers=auth_headers(init),
        )

    webhook_result, poll_resp = await asyncio.gather(_run_webhook(), _run_poll())

    assert webhook_result.get("ok") is True
    assert poll_resp.status_code == 200, poll_resp.text

    async with async_session() as session:
        owner = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        # Exactly the invoice amount (NOT 2x). Pre-fix this would be
        # 2 * invoice_amount, or one of the two transactions would
        # deadlock-abort.
        assert Decimal(str(owner.balance)) == invoice_amount

        inv_row = (
            await session.execute(select(Invoice).where(Invoice.provider_invoice_id == provider_id))
        ).scalar_one()
        assert inv_row.status == InvoiceStatus.paid

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
async def test_concurrent_paid_and_expired_webhook_keeps_paid_status_sticky(client):
    """V5-B-1 follow-up — concurrent ``invoice_paid`` and
    ``invoice_expired`` webhooks for the SAME pending
    ``WalletDeposit`` must end with ``status=paid`` (sticky), the
    balance credited exactly once, and exactly one notification.

    Pre-fix ``handle_invoice_expired`` did NOT take a row lock while
    ``handle_invoice_paid`` did (V5-B-1). The expired webhook could
    snapshot-read ``status=pending`` and, after the paid transaction
    commits, flush ``UPDATE wallet_deposits SET status='expired'``,
    silently flipping a freshly-paid row to ``expired`` even though
    the balance was already credited. Fix: ``handle_invoice_expired``
    now also passes ``lock=True`` so the existing ``status in
    (paid, expired, refunded)`` recheck runs against the locked,
    post-paid value.
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

    init = signed_init_data(7503, "race_paid_vs_expired")
    await setup_pin(client, init)

    deposit_amount = Decimal("21.0")
    provider_id = "cb-race-paid-vs-expired-1"

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 7503)
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

    paid_body = json.dumps(
        {
            "update_type": "invoice_paid",
            "payload": {"invoice_id": provider_id, "status": "paid"},
        }
    ).encode()
    expired_body = json.dumps(
        {
            "update_type": "invoice_expired",
            "payload": {"invoice_id": provider_id, "status": "expired"},
        }
    ).encode()
    paid_headers = {
        "crypto-pay-api-signature": _sign_webhook(paid_body),
        "Content-Type": "application/json",
    }
    expired_headers = {
        "crypto-pay-api-signature": _sign_webhook(expired_body),
        "Content-Type": "application/json",
    }

    paid_resp, expired_resp = await asyncio.gather(
        client.post("/api/payments/webhook/cryptobot", content=paid_body, headers=paid_headers),
        client.post(
            "/api/payments/webhook/cryptobot", content=expired_body, headers=expired_headers
        ),
    )

    assert paid_resp.status_code == 200, paid_resp.text
    assert expired_resp.status_code == 200, expired_resp.text
    assert paid_resp.json()["ok"] is True
    assert expired_resp.json()["ok"] is True

    async with async_session() as session:
        dep = (
            await session.execute(
                select(WalletDeposit).where(WalletDeposit.provider_invoice_id == provider_id)
            )
        ).scalar_one()
        # ``paid`` is sticky — never clobbered by a concurrent
        # ``expired`` delivery.
        assert dep.status == WalletDepositStatus.paid

        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == user_id,
                    UserBalance.currency_id == usdt_id,
                )
            )
        ).scalar_one()
        # Balance equals the deposit amount exactly: not 0
        # (would mean the expired path won and undid the credit), not
        # 2x (would mean both paths credited), not negative.
        assert Decimal(str(bal.amount)) == deposit_amount

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
async def test_concurrent_first_touch_creates_exactly_one_user(client):
    """Comment 28 (H) — N parallel first-touch requests for the same
    brand-new ``tg_user_id`` must end with exactly one ``users`` row.

    Pre-fix, ``get_current_user`` did a plain ``SELECT`` + ``session.add``
    sequence: when the TMA frontend mounts it fires
    ``/api/me``, ``/api/wallet/balances``, ``/api/notifications`` and
    ``/api/categories`` in parallel, all four saw no row, all four
    called ``session.add(User(...))``, the loser of the commit race
    blew up with ``IntegrityError`` on the ``users.tg_user_id`` unique
    constraint and the request 500'd. The fix is an
    ``INSERT ... ON CONFLICT (tg_user_id) DO NOTHING`` followed by a
    re-SELECT to load whichever row actually persisted.

    Driving the four real endpoints the frontend hits — instead of
    just /api/me four times — also covers any per-router middleware
    quirks (e.g. an extra ``get_current_user`` resolution path).
    """
    from backend.app.db import async_session
    from backend.app.models import User

    tg_user_id = 8801
    init = signed_init_data(tg_user_id, "race_first_touch")
    headers = auth_headers(init)

    r1, r2, r3, r4 = await asyncio.gather(
        client.get("/api/me", headers=headers),
        client.get("/api/wallet/balances", headers=headers),
        client.get("/api/notifications", headers=headers),
        client.get("/api/categories", headers=headers),
    )

    for label, resp in zip(("me", "balances", "notifications", "categories"), (r1, r2, r3, r4)):
        assert resp.status_code == 200, f"{label}: {resp.status_code} {resp.text}"

    async with async_session() as session:
        rows = (
            (await session.execute(select(User).where(User.tg_user_id == tg_user_id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1, [r.id for r in rows]


@pytest.mark.asyncio
async def test_concurrent_me_for_new_user_is_idempotent(client):
    """Comment 28 (H) — same race, narrower probe: just /api/me four
    times in parallel. Asserts on both the row count (exactly one)
    and that every request returned a consistent user id.

    The four-endpoint variant above exercises the realistic mount
    storm; this one is a focused regression that fails fast if
    ``get_current_user`` ever drops the ON CONFLICT path.
    """
    from backend.app.db import async_session
    from backend.app.models import User

    tg_user_id = 8802
    init = signed_init_data(tg_user_id, "race_me_only")
    headers = auth_headers(init)

    results = await asyncio.gather(
        client.get("/api/me", headers=headers),
        client.get("/api/me", headers=headers),
        client.get("/api/me", headers=headers),
        client.get("/api/me", headers=headers),
    )
    statuses = [r.status_code for r in results]
    assert statuses == [200, 200, 200, 200], statuses

    seen_ids = {r.json()["id"] for r in results}
    assert len(seen_ids) == 1, seen_ids

    async with async_session() as session:
        rows = (
            (await session.execute(select(User).where(User.tg_user_id == tg_user_id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
