"""``sweep_expired_deposits`` notifies the user.

Originally the sweep silently flipped ``pending`` rows to ``expired``
and the deposit just vanished from the TMA's "pending" tab. We now
insert a ``deposits``-bucket notification + dispatch DM/WS so the
user actually finds out the invoice they walked away from closed.

Mocks ``_safe_send_dm`` so the test doesn't touch aiogram.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from backend.app.config import settings
from backend.app.db import async_session
from backend.app.models import (
    Currency,
    Notification,
    NotificationType,
    User,
    WalletDeposit,
    WalletDepositStatus,
)
from backend.app.services_wallet import sweep_expired_deposits
from backend.app.time_utils import utcnow


async def _seed_user(tg_user_id: int) -> int:
    async with async_session() as session:
        u = User(
            tg_user_id=tg_user_id,
            username=f"u{tg_user_id}",
            display_name="x",
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u.id


async def _seed_stale_deposit(user_id: int, provider_invoice_id: str) -> int:
    """Create a pending deposit timestamped past the sweep cutoff."""
    expiry = int(settings.wallet_deposit_expiry_seconds)
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        dep = WalletDeposit(
            user_id=user_id,
            currency_id=usdt.id,
            amount=5.0,
            provider_invoice_id=provider_invoice_id,
            pay_url="http://example.com/pay",
            status=WalletDepositStatus.pending,
        )
        session.add(dep)
        await session.flush()
        dep.created_at = utcnow() - timedelta(seconds=expiry + 60)
        await session.commit()
        return dep.id


@pytest.fixture
def captured_dms(monkeypatch):
    """Replace ``_safe_send_dm`` and collect the DMs it would have sent."""
    sent: list[tuple[int, str, str | None]] = []

    async def fake_send(tg_user_id, text, *, notif_type=None, payload=None):
        sent.append((tg_user_id, text, notif_type))

    from backend.app import notifier

    monkeypatch.setattr(notifier, "_safe_send_dm", fake_send)
    return sent


async def test_sweep_inserts_notification_and_sends_dm(client, captured_dms):
    """A stale pending deposit flips to expired AND inserts exactly
    one ``deposits`` notification + dispatches one DM."""
    user_id = await _seed_user(70001)
    await _seed_stale_deposit(user_id, "sweep-1")

    async with async_session() as session:
        affected = await sweep_expired_deposits(session)
    assert affected == 1

    async with async_session() as session:
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
        assert len(notifs) == 1
        assert "истёк" in notifs[0].title.lower()
        assert notifs[0].payload is not None
        assert "deposit_id" in notifs[0].payload

    assert len(captured_dms) == 1
    tg_id, text, notif_type = captured_dms[0]
    assert tg_id == 70001
    assert "истёк" in text.lower() or "ист" in text.lower()
    assert notif_type == "deposits"


async def test_sweep_skips_user_when_no_pending(client, captured_dms):
    """Sweep over a clean DB inserts no notifications and sends no DMs."""
    async with async_session() as session:
        affected = await sweep_expired_deposits(session)
    assert affected == 0
    assert captured_dms == []
