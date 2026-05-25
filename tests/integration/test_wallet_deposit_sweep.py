"""M-6 — auto-expire stale ``WalletDeposit(status=pending)`` rows.

Before the fix, a deposit row that the user clicked "pay" on but never
finished would sit in ``pending`` forever because CryptoBot stops
emitting webhooks once the invoice has expired on their side. The
``sweep_expired_deposits`` helper now closes the loop by flipping any
``pending`` row older than ``settings.wallet_deposit_expiry_seconds``
to ``expired`` on a periodic background task. These tests exercise
the sweep directly (the background loop itself is disabled in the
test conftest to keep things deterministic).
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from backend.app.config import settings
from backend.app.db import async_session
from backend.app.models import (
    Currency,
    User,
    WalletDeposit,
    WalletDepositStatus,
)
from backend.app.services_wallet import sweep_expired_deposits
from backend.app.time_utils import utcnow


async def _seed_user(tg_user_id: int = 9001) -> int:
    async with async_session() as session:
        u = User(tg_user_id=tg_user_id, username=f"u{tg_user_id}", display_name="x")
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u.id


async def _seed_deposit(
    user_id: int,
    *,
    status: WalletDepositStatus,
    age_seconds: int,
    provider_invoice_id: str,
) -> int:
    """Create a deposit row with a hand-stamped ``created_at`` offset.

    ``age_seconds`` is interpreted as "this row was created N seconds
    ago". The sweep cutoff uses the same clock so we don't have to
    monkey-patch anything.
    """
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        dep = WalletDeposit(
            user_id=user_id,
            currency_id=usdt.id,
            amount=10.0,
            provider_invoice_id=provider_invoice_id,
            pay_url="http://example.com/pay",
            status=status,
        )
        session.add(dep)
        await session.flush()
        dep.created_at = utcnow() - timedelta(seconds=age_seconds)
        await session.commit()
        return dep.id


async def test_sweep_marks_stale_pending_as_expired():
    """Three pending deposits older than the cutoff all flip to expired
    in a single sweep pass. A fresh pending row created inside the
    grace window stays pending so the sweep can't accidentally close a
    transaction the user is still completing."""
    user_id = await _seed_user(9001)

    expiry = int(settings.wallet_deposit_expiry_seconds)
    stale_ids = [
        await _seed_deposit(
            user_id,
            status=WalletDepositStatus.pending,
            age_seconds=expiry + 60 + i * 5,
            provider_invoice_id=f"stale-{i}",
        )
        for i in range(3)
    ]
    fresh_id = await _seed_deposit(
        user_id,
        status=WalletDepositStatus.pending,
        age_seconds=10,
        provider_invoice_id="fresh-1",
    )

    async with async_session() as session:
        affected = await sweep_expired_deposits(session)
    assert affected == 3

    async with async_session() as session:
        statuses = {
            d.id: d.status
            for d in (
                (
                    await session.execute(
                        select(WalletDeposit).where(WalletDeposit.id.in_([*stale_ids, fresh_id]))
                    )
                )
                .scalars()
                .all()
            )
        }

    for sid in stale_ids:
        assert statuses[sid] == WalletDepositStatus.expired
    assert statuses[fresh_id] == WalletDepositStatus.pending


async def test_sweep_leaves_terminal_states_alone():
    """``paid`` / ``expired`` / ``refunded`` rows are skipped even when
    they're older than the cutoff — sweep only touches ``pending``."""
    user_id = await _seed_user(9002)

    expiry = int(settings.wallet_deposit_expiry_seconds)
    terminal_states = (
        WalletDepositStatus.paid,
        WalletDepositStatus.expired,
        WalletDepositStatus.refunded,
    )
    ids: dict[WalletDepositStatus, int] = {}
    for i, st in enumerate(terminal_states):
        ids[st] = await _seed_deposit(
            user_id,
            status=st,
            age_seconds=expiry + 60 + i * 5,
            provider_invoice_id=f"term-{st.value}",
        )

    async with async_session() as session:
        affected = await sweep_expired_deposits(session)
    assert affected == 0

    async with async_session() as session:
        for st, dep_id in ids.items():
            row = (
                await session.execute(select(WalletDeposit).where(WalletDeposit.id == dep_id))
            ).scalar_one()
            assert row.status == st


async def test_sweep_is_idempotent():
    """Running the sweep twice doesn't re-touch already-expired rows."""
    user_id = await _seed_user(9003)

    expiry = int(settings.wallet_deposit_expiry_seconds)
    await _seed_deposit(
        user_id,
        status=WalletDepositStatus.pending,
        age_seconds=expiry + 600,
        provider_invoice_id="stale-once",
    )

    async with async_session() as session:
        first = await sweep_expired_deposits(session)
    async with async_session() as session:
        second = await sweep_expired_deposits(session)
    assert first == 1
    assert second == 0
