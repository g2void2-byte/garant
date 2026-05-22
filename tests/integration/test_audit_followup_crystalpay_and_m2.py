"""Two final audit follow-ups landed as a tests-only PR.

* **§6.5** — the audit asked for a check that *all* terminal Crystalpay
  invoice states map onto our wallet-deposit lifecycle. The existing
  ``test_crystalpay_webhook.py`` pins ``payed`` (→ credit) and
  ``unavailable`` (→ expire); this file adds the missing ``failed`` →
  expire path, plus a regression for the non-terminal "ignored_state"
  branch where ``handle_crystalpay_invoice`` must leave the deposit
  untouched and surface a structured ``crystalpay.webhook.ignored_state``
  log event.

* **§15.10** — the audit explicitly noted that
  ``alembic/versions/s1a2b3c4d5e6_m2_service_currency_id`` was the one
  migration it did not read in detail. This file pins the post-migration
  shape against ``information_schema`` so any future refactor that
  drops the FK, the index, or the nullable bit fails the test loudly.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select, text

from backend.app.db import async_session
from tests.helpers import get_user_id_by_tg, setup_pin, signed_init_data


def _sign(invoice_id: str, salt: str) -> str:
    return hashlib.sha1(f"{invoice_id}:{salt}".encode()).hexdigest()


# ── §6.5 — failed state expires the deposit ─────────────────────────


async def test_6_5_webhook_failed_expires_deposit(client):
    """``state=failed`` is the third terminal Crystalpay state. The
    handler must treat it identically to ``unavailable``: lock the
    deposit row, flip it to ``expired``, and insert a "deposit
    expired" notification so the user isn't left wondering.
    """
    from backend.app.config import settings
    from backend.app.models import (
        Currency,
        Notification,
        NotificationType,
        WalletDeposit,
        WalletDepositProvider,
        WalletDepositStatus,
    )

    init = signed_init_data(46501, "audit65failed")
    await setup_pin(client, init)

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 46501)
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        dep = WalletDeposit(
            user_id=user_id,
            currency_id=usdt.id,
            amount=4.25,
            provider=WalletDepositProvider.crystalpay,
            provider_invoice_id="cp-fail-1",
            pay_url="https://pay/cp-fail-1",
            status=WalletDepositStatus.pending,
        )
        session.add(dep)
        await session.commit()
        deposit_id = dep.id

    body = {
        "id": "cp-fail-1",
        "state": "failed",
        "signature": _sign("cp-fail-1", settings.crystalpay_secret),
    }
    resp = await client.post("/api/payments/webhook/crystalpay", json=body)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["ok"] is True
    assert payload.get("expired") is True

    async with async_session() as session:
        dep = await session.get(WalletDeposit, deposit_id)
        assert dep is not None
        assert dep.status == WalletDepositStatus.expired, (
            f"`state=failed` should map to expired, got {dep.status!r}"
        )

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
        assert len(notifs) == 1, "`state=failed` must surface a `deposits` notification to the user"
        assert "истёк" in notifs[0].title.lower()


# ── §6.5 — non-terminal state is ignored without mutation ───────────


async def test_6_5_webhook_unknown_state_returns_ok_and_leaves_row_pending(client):
    """The handler must NOT mutate the deposit for non-terminal states
    (``waiting``, ``processing``, anything the docs haven't enumerated).
    Pre-fix we'd want a guarantee that a future Crystalpay state
    change can't accidentally credit or expire a deposit just by
    flipping the dispatch table; we currently `return {"ok": True,
    "ignored_state": ...}` and leave the row in ``pending``. The
    standalone "ignored_state" branch is also the one the M-6 sweep
    relies on to eventually close stale deposits.
    """
    from backend.app.config import settings
    from backend.app.models import (
        Currency,
        Notification,
        NotificationType,
        WalletDeposit,
        WalletDepositProvider,
        WalletDepositStatus,
    )

    init = signed_init_data(46502, "audit65ignored")
    await setup_pin(client, init)

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 46502)
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        dep = WalletDeposit(
            user_id=user_id,
            currency_id=usdt.id,
            amount=9.99,
            provider=WalletDepositProvider.crystalpay,
            provider_invoice_id="cp-ignore-1",
            pay_url="https://pay/cp-ignore-1",
            status=WalletDepositStatus.pending,
        )
        session.add(dep)
        await session.commit()
        deposit_id = dep.id

    body = {
        "id": "cp-ignore-1",
        # Not in {"payed", "unavailable", "failed"}; the handler treats
        # this as "still in flight, do nothing".
        "state": "processing",
        "signature": _sign("cp-ignore-1", settings.crystalpay_secret),
    }
    resp = await client.post("/api/payments/webhook/crystalpay", json=body)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["ok"] is True
    assert payload.get("ignored_state") == "processing", payload

    async with async_session() as session:
        dep = await session.get(WalletDeposit, deposit_id)
        assert dep is not None
        assert dep.status == WalletDepositStatus.pending, (
            "non-terminal state must not mutate the deposit row"
        )

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
        assert notifs == [], "non-terminal state must not emit a `deposits` notification"


# ── §15.10 — services.currency_id physical shape after M-2 ──────────


async def test_15_10_services_currency_id_column_is_nullable_int():
    """Migration ``s1a2b3c4d5e6_m2_service_currency_id`` adds the column,
    a btree index, and a FK to ``currencies.id``. Pin the post-migration
    shape against ``information_schema`` so a future refactor that
    accidentally drops the FK or flips nullability is loud.
    """
    async with async_session() as session:
        # Column shape.
        col = (
            await session.execute(
                text(
                    "SELECT data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'services' AND column_name = 'currency_id'"
                )
            )
        ).first()
        assert col is not None, "services.currency_id column missing"
        data_type, is_nullable = col
        assert data_type == "integer", f"expected integer, got {data_type!r}"
        assert is_nullable == "YES", (
            "services.currency_id must stay nullable so existing rows default to NULL "
            "(== USD); the M-2 migration explicitly added it as nullable=True"
        )

        # Btree index.
        idx = (
            await session.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE tablename = 'services' "
                    "AND indexname = 'ix_services_currency_id'"
                )
            )
        ).first()
        assert idx is not None, (
            "ix_services_currency_id is missing — admin filters / joins by currency "
            "will sequential-scan the services table"
        )

        # Foreign key to currencies(id).
        fk = (
            await session.execute(
                text(
                    "SELECT confrelid::regclass::text AS referenced "
                    "FROM pg_constraint "
                    "WHERE conname = 'fk_services_currency_id'"
                )
            )
        ).first()
        assert fk is not None, "fk_services_currency_id constraint missing"
        assert fk[0] == "currencies", (
            f"fk_services_currency_id should reference currencies(id), got {fk[0]!r}"
        )
