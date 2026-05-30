"""Regression tests for the three Critical findings in the May code review:

* **C1** ``create_withdrawal`` race-condition — two concurrent withdraw
  requests against the same balance must not both succeed when the user
  doesn't have enough funds for both.
* **C2** ``create_deal`` / ``_debit`` race-condition — two concurrent
  deal-creation requests against the same buyer balance must not both
  succeed when the user doesn't have enough funds for both.

C3 (``manual_deposit`` 500) was retired together with the legacy USD
``Invoice`` ledger by H-1; the manual-deposit endpoint and its
collision-prone ``provider_invoice_id`` are gone.

The fix for C1 and C2 is a ``FOR UPDATE`` row lock on ``UserBalance``.

V5-B-1 — concurrency fix covered here:

* webhook → ``services_payments.handle_invoice_paid`` →
  ``services_wallet.credit_deposit`` for the multi-currency
  ``WalletDeposit`` path.

It closes the same shape of race that V5-B-2 closed for the legacy
``Invoice`` path before H-1 retired that path: two concurrent webhook
deliveries (CryptoBot retry / proxy duplication) read the ``pending``
row, both pass the status check, both credit. Fix is
``SELECT ... FOR UPDATE`` on the deposit row inside
``handle_invoice_paid`` plus a ``FOR UPDATE`` lock on the balance
row inside ``credit_deposit``, with a status recheck after each lock
so the loser of the race exits idempotently.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from decimal import Decimal

import pytest
from sqlalchemy import select

from tests.helpers import (
    auth_headers,
    credit_balance,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
    with_totp,
)


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
async def test_concurrent_deal_creation_cannot_overdraw(client, _stub_cryptopay):
    """C2 — two parallel ``create_deal`` requests must not overspend.

    Buyer has 100 USDT; two simultaneous deals of 70 USDT each are
    submitted. Each costs 70 locked principal (P10 — commission is
    charged via the deposit invoice in ``create_deal_with_topup`` and
    is not added to ``UserBalance.locked`` on this legacy
    balance-only path). Without the ``FOR UPDATE`` lock on ``_debit``
    both pass the balance check; with the lock one returns 400
    ("Недостаточно средств").
    """
    from backend.app.db import async_session
    from backend.app.models import Currency, DealStatus, UserBalance

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
        "amount": 70.0,
        "description": "race test",
        "currency_code": "USDT",
    }

    r1, r2 = await asyncio.gather(
        client.post("/api/deals", json=body, headers=headers),
        client.post("/api/deals", json=body, headers=headers),
    )

    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [201, 201], (r1.status_code, r1.text, r2.status_code, r2.text)
    deal_statuses = {r1.json()["status"], r2.json()["status"]}
    assert deal_statuses == {
        DealStatus.pending_confirmation.value,
        DealStatus.pending_topup.value,
    }

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
        # Only one deal got debited: 100 − 70 = 30 spendable,
        # 70 locked (principal only — see docstring). The balance
        # must never go negative.
        assert float(bal.amount) >= 0
        assert float(bal.amount) == pytest.approx(26.5)
        assert float(bal.locked) == pytest.approx(70.0)


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
            # Audit L-9 — ``handle_invoice_paid`` now compares
            # ``payload["amount"]`` against the seeded ``wallet.amount``
            # before crediting; the real Crypto Pay webhook always
            # ships ``amount`` so we mirror the production shape.
            "payload": {
                "invoice_id": provider_id,
                "status": "paid",
                "amount": str(deposit_amount),
            },
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

    # Audit L-9 — include the reported amount so
    # ``handle_invoice_paid`` passes the amount-mismatch guard.
    payload = {
        "invoice_id": provider_id,
        "status": "paid",
        "amount": str(deposit_amount),
    }

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
            # Audit L-9 — mirror the real Crypto Pay payload shape.
            "payload": {
                "invoice_id": provider_id,
                "status": "paid",
                "amount": str(deposit_amount),
            },
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

    for label, resp in zip(
        ("me", "balances", "notifications", "categories"),
        (r1, r2, r3, r4),
        strict=True,
    ):
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


@pytest.mark.asyncio
async def test_concurrent_admin_mark_paid_two_deposits_credits_both(client):
    """CRIT #3 — two parallel ``POST /api/admin/deposits/{id}/mark-paid``
    for two distinct ``pending`` deposits of the SAME user must credit
    the balance for both without dropping either increment.

    Pre-fix ``mark_paid`` called ``get_or_create_balance`` (no row lock),
    so two concurrent calls read the same ``UserBalance.amount``
    snapshot, each added their own deposit amount to that snapshot,
    and the loser of the commit race overwrote the winner — the
    user lost one of the two credits silently. The fix is a
    ``SELECT ... FOR UPDATE`` on the ``UserBalance`` row inside the
    handler (mirrors ``refund_deposit`` and
    ``services_wallet.credit_deposit``).
    """
    from sqlalchemy import select

    from backend.app.db import async_session
    from backend.app.models import (
        AdminAuditLog,
        Currency,
        User,
        UserBalance,
        WalletDeposit,
        WalletDepositStatus,
    )

    admin_init = signed_init_data(8901, "race_mp_admin")
    user_init = signed_init_data(8902, "race_mp_user")

    # Bootstrap both rows via /api/me; promote the admin.
    admin_resp = await client.get("/api/me", headers=auth_headers(admin_init))
    assert admin_resp.status_code == 200, admin_resp.text
    user_resp = await client.get("/api/me", headers=auth_headers(user_init))
    assert user_resp.status_code == 200, user_resp.text
    user_id = user_resp.json()["id"]
    async with async_session() as session:
        admin_row = await session.get(User, admin_resp.json()["id"])
        assert admin_row is not None
        admin_row.is_admin = True
        await session.commit()

    # Create two ``pending`` deposits for the same user directly in
    # the DB so we can race the mark-paid calls without going through
    # the CryptoBot mock first.
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        d1 = WalletDeposit(
            user_id=user_id,
            currency_id=usdt.id,
            amount=Decimal("11.0"),
            provider_invoice_id="cb-race-mp-1",
            pay_url="http://example.com/pay/1",
            status=WalletDepositStatus.pending,
        )
        d2 = WalletDeposit(
            user_id=user_id,
            currency_id=usdt.id,
            amount=Decimal("22.0"),
            provider_invoice_id="cb-race-mp-2",
            pay_url="http://example.com/pay/2",
            status=WalletDepositStatus.pending,
        )
        session.add_all([d1, d2])
        await session.commit()
        d1_id, d2_id = d1.id, d2.id
        usdt_id = usdt.id

    headers = with_totp(auth_headers(admin_init))
    r1, r2 = await asyncio.gather(
        client.post(f"/api/admin/deposits/{d1_id}/mark-paid", json={}, headers=headers),
        client.post(f"/api/admin/deposits/{d2_id}/mark-paid", json={}, headers=headers),
    )
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text

    async with async_session() as session:
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == user_id,
                    UserBalance.currency_id == usdt_id,
                )
            )
        ).scalar_one()
        # Pre-fix: the loser overwrote the winner so amount was 11 OR
        # 22 — never the sum. With ``FOR UPDATE`` the second handler
        # waits for the first to commit, then reads the
        # post-credit row and adds its own deposit on top.
        assert Decimal(str(bal.amount)) == Decimal("33.0")

        # Both deposit rows are marked paid (each handler also locks
        # the WalletDeposit row separately).
        for dep_id in (d1_id, d2_id):
            dep = await session.get(WalletDeposit, dep_id)
            assert dep is not None
            assert dep.status == WalletDepositStatus.paid

        # Each successful mark-paid writes one audit row.
        audits = (
            (
                await session.execute(
                    select(AdminAuditLog).where(AdminAuditLog.action == "deposit.mark_paid")
                )
            )
            .scalars()
            .all()
        )
        assert len(audits) >= 2
