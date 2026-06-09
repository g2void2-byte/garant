"""Crystalpay webhook router + handler.

Mirrors ``test_cryptobot_webhook.py`` for the Crystalpay v3 envelope:

* a valid ``state=payed`` delivery credits the user balance,
* a valid ``state=unavailable`` delivery flips the deposit to
  ``expired`` *and* inserts a ``deposits`` notification (which lands
  in WS + DM via the notifier),
* a bad signature is rejected with 401,
* an unconfigured secret returns 503.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select

from tests.helpers import get_user_id_by_tg, setup_pin, signed_init_data


def _sign(invoice_id: str, salt: str) -> str:
    return hashlib.sha1(f"{invoice_id}:{salt}".encode()).hexdigest()


async def test_webhook_payed_credits_pending_deposit_and_is_idempotent(client):
    from backend.app.config import settings
    from backend.app.db import async_session
    from backend.app.models import (
        Currency,
        Notification,
        NotificationType,
        UserBalance,
        WalletDeposit,
        WalletDepositProvider,
        WalletDepositStatus,
    )

    init_data = signed_init_data(40001, "alice-cp")
    await setup_pin(client, init_data)

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 40001)
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        session.add(
            WalletDeposit(
                user_id=user_id,
                currency_id=usdt.id,
                amount=7.5,
                provider=WalletDepositProvider.crystalpay,
                provider_invoice_id="cp-100",
                pay_url="https://pay.crystalpay.io/cp-100",
                status=WalletDepositStatus.pending,
            )
        )
        await session.commit()

    body = {
        "id": "cp-100",
        "state": "payed",
        "amount": "7.5",
        "currency": "USDT",
        "signature": _sign("cp-100", settings.crystalpay_secret),
    }
    resp = await client.post("/api/payments/webhook/crystalpay", json=body)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["ok"] is True
    assert payload.get("kind") == "wallet"

    async with async_session() as session:
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == user_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        assert float(bal.amount) == 7.5

    # Second call: idempotent — no double credit.
    resp2 = await client.post("/api/payments/webhook/crystalpay", json=body)
    assert resp2.status_code == 200
    assert resp2.json().get("already_paid") is True or resp2.json().get("duplicate") is True

    async with async_session() as session:
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == user_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        assert float(bal.amount) == 7.5

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
        # credit_deposit always inserts a "deposit credited"
        # notification — verify it landed exactly once.
        assert len(notifs) == 1


async def test_webhook_unavailable_expires_deposit_and_inserts_notif(client):
    from backend.app.config import settings
    from backend.app.db import async_session
    from backend.app.models import (
        Currency,
        Notification,
        NotificationType,
        WalletDeposit,
        WalletDepositProvider,
        WalletDepositStatus,
    )

    init_data = signed_init_data(40002, "bob-cp")
    await setup_pin(client, init_data)

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 40002)
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        dep = WalletDeposit(
            user_id=user_id,
            currency_id=usdt.id,
            amount=3.0,
            provider=WalletDepositProvider.crystalpay,
            provider_invoice_id="cp-200",
            pay_url="https://pay/cp-200",
            status=WalletDepositStatus.pending,
        )
        session.add(dep)
        await session.commit()
        deposit_id = dep.id

    body = {
        "id": "cp-200",
        "state": "unavailable",
        "signature": _sign("cp-200", settings.crystalpay_secret),
    }
    resp = await client.post("/api/payments/webhook/crystalpay", json=body)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["ok"] is True
    assert payload.get("expired") is True

    async with async_session() as session:
        dep = await session.get(WalletDeposit, deposit_id)
        assert dep is not None
        assert dep.status == WalletDepositStatus.expired

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
        # No credit fired (it expired), so the only notification is
        # the "expired" one inserted by the handler.
        assert len(notifs) == 1
        assert "истёк" in notifs[0].title.lower()


async def test_webhook_bad_signature_returns_401(client):
    from backend.app.db import async_session
    from backend.app.models import (
        Currency,
        WalletDeposit,
        WalletDepositProvider,
        WalletDepositStatus,
    )

    init_data = signed_init_data(40003, "mallory-cp")
    await setup_pin(client, init_data)

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 40003)
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        session.add(
            WalletDeposit(
                user_id=user_id,
                currency_id=usdt.id,
                amount=1.0,
                provider=WalletDepositProvider.crystalpay,
                provider_invoice_id="cp-300",
                pay_url="https://pay/cp-300",
                status=WalletDepositStatus.pending,
            )
        )
        await session.commit()

    body = {
        "id": "cp-300",
        "state": "payed",
        "signature": "deadbeef" * 5,  # bogus
    }
    resp = await client.post("/api/payments/webhook/crystalpay", json=body)
    assert resp.status_code == 401, resp.text


async def test_webhook_unconfigured_secret_returns_503(client, monkeypatch):
    from backend.app.config import settings

    monkeypatch.setattr(settings, "crystalpay_secret", "")
    body = {"id": "cp-anything", "state": "payed", "signature": "x"}
    resp = await client.post("/api/payments/webhook/crystalpay", json=body)
    assert resp.status_code == 503, resp.text


async def test_webhook_unknown_invoice_returns_200_ok_false(client):
    from backend.app.config import settings

    body = {
        "id": "cp-does-not-exist",
        "state": "payed",
        "signature": _sign("cp-does-not-exist", settings.crystalpay_secret),
    }
    resp = await client.post("/api/payments/webhook/crystalpay", json=body)
    # Crystalpay would retry on non-200 — we ack the delivery and
    # surface ``ok: false`` in the body so the webhook log captures
    # the miss.
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload.get("reason") == "unknown invoice"


async def test_webhook_corrected_same_state_payload_is_not_suppressed(client):
    """A changed Crystalpay payload for the same invoice/state must be
    processed instead of replaying the first event's cached result.

    Crystalpay signs only by invoice id, so the corrected delivery has
    the same ``id`` and ``state`` but a different ``amount``. A coarse
    ``event_id = id:state`` would keep returning the initial amount-
    mismatch result and leave the deposit pending forever.
    """
    from backend.app.config import settings
    from backend.app.db import async_session
    from backend.app.models import (
        Currency,
        UserBalance,
        WalletDeposit,
        WalletDepositProvider,
        WalletDepositStatus,
    )

    init_data = signed_init_data(40004, "corrected-cp")
    await setup_pin(client, init_data)

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 40004)
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        dep = WalletDeposit(
            user_id=user_id,
            currency_id=usdt.id,
            amount=10,
            provider=WalletDepositProvider.crystalpay,
            provider_invoice_id="cp-corrected-1",
            pay_url="https://pay/cp-corrected-1",
            status=WalletDepositStatus.pending,
        )
        session.add(dep)
        await session.commit()
        dep_id = dep.id
        currency_id = usdt.id

    base = {
        "id": "cp-corrected-1",
        "state": "payed",
        "currency": "USDT",
        "signature": _sign("cp-corrected-1", settings.crystalpay_secret),
    }
    bad_resp = await client.post(
        "/api/payments/webhook/crystalpay",
        json={**base, "amount": "1"},
    )
    assert bad_resp.status_code == 200, bad_resp.text
    assert bad_resp.json().get("reason") == "amount mismatch"

    async with async_session() as session:
        dep = await session.get(WalletDeposit, dep_id)
        assert dep is not None
        assert dep.status == WalletDepositStatus.pending

    fixed_resp = await client.post(
        "/api/payments/webhook/crystalpay",
        json={**base, "amount": "10"},
    )
    assert fixed_resp.status_code == 200, fixed_resp.text
    assert fixed_resp.json()["ok"] is True

    async with async_session() as session:
        dep = await session.get(WalletDeposit, dep_id)
        assert dep is not None
        assert dep.status == WalletDepositStatus.paid
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == user_id,
                    UserBalance.currency_id == currency_id,
                )
            )
        ).scalar_one()
        assert float(bal.amount) == 10.0
