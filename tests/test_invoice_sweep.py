"""V5-B-7 — auto-expire stale legacy ``Invoice(status=pending)`` rows.

Before the fix, an ``Invoice`` row created by the legacy
``POST /api/payments/deposit`` (``manual_deposit``) sat in ``pending``
forever if the user never finished paying. Unlike the real CryptoBot
wallet-deposit flow, these are placeholder rows that no webhook will
ever update — the provider id is hand-stamped, not issued by
CryptoBot. The ``sweep_expired_invoices`` helper now closes the loop
by flipping any ``pending`` row older than
``settings.invoice_expiry_seconds`` to ``expired`` on a periodic
background task. These tests exercise the sweep directly (the
background loop itself is disabled in the test conftest to keep
things deterministic).
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from backend.app.config import settings
from backend.app.db import async_session
from backend.app.models import (
    Invoice,
    InvoiceProvider,
    InvoiceStatus,
    User,
)
from backend.app.services import sweep_expired_invoices
from backend.app.time_utils import utcnow


async def _seed_user(tg_user_id: int = 7001) -> int:
    async with async_session() as session:
        u = User(tg_user_id=tg_user_id, username=f"u{tg_user_id}", display_name="x")
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u.id


async def _seed_invoice(
    owner_id: int,
    *,
    status: InvoiceStatus,
    age_seconds: int,
) -> int:
    """Create an invoice row with a hand-stamped ``created_at`` offset.

    ``age_seconds`` is interpreted as "this row was created N seconds
    ago". The sweep cutoff uses the same clock so we don't have to
    monkey-patch anything. ``provider_invoice_id`` is UUID-suffixed to
    sidestep the UNIQUE constraint when seeding multiple rows.
    """
    async with async_session() as session:
        inv = Invoice(
            owner_id=owner_id,
            provider=InvoiceProvider.cryptobot,
            provider_invoice_id=f"sweep-test-{uuid4().hex}",
            amount=10.0,
            status=status,
        )
        session.add(inv)
        await session.flush()
        inv.created_at = utcnow() - timedelta(seconds=age_seconds)
        await session.commit()
        return inv.id


async def test_sweep_marks_stale_pending_invoices_as_expired():
    """Three pending invoices older than the cutoff all flip to expired
    in a single sweep pass. A fresh pending row created inside the
    grace window stays pending so the sweep can't accidentally close a
    transaction the user is still completing."""
    owner_id = await _seed_user(7001)

    expiry = int(settings.invoice_expiry_seconds)
    stale_ids = [
        await _seed_invoice(
            owner_id,
            status=InvoiceStatus.pending,
            age_seconds=expiry + 60 + i * 5,
        )
        for i in range(3)
    ]
    fresh_id = await _seed_invoice(
        owner_id,
        status=InvoiceStatus.pending,
        age_seconds=10,
    )

    async with async_session() as session:
        affected = await sweep_expired_invoices(session)
    assert affected == 3

    async with async_session() as session:
        statuses = {
            i.id: i.status
            for i in (
                (
                    await session.execute(
                        select(Invoice).where(Invoice.id.in_([*stale_ids, fresh_id]))
                    )
                )
                .scalars()
                .all()
            )
        }

    for sid in stale_ids:
        assert statuses[sid] == InvoiceStatus.expired
    assert statuses[fresh_id] == InvoiceStatus.pending


async def test_sweep_leaves_terminal_invoice_states_alone():
    """``paid`` / ``expired`` rows are skipped even when they're older
    than the cutoff — sweep only touches ``pending``."""
    owner_id = await _seed_user(7002)

    expiry = int(settings.invoice_expiry_seconds)
    terminal_states = (
        InvoiceStatus.paid,
        InvoiceStatus.expired,
    )
    ids: dict[InvoiceStatus, int] = {}
    for i, st in enumerate(terminal_states):
        ids[st] = await _seed_invoice(
            owner_id,
            status=st,
            age_seconds=expiry + 60 + i * 5,
        )

    async with async_session() as session:
        affected = await sweep_expired_invoices(session)
    assert affected == 0

    async with async_session() as session:
        for st, inv_id in ids.items():
            row = (await session.execute(select(Invoice).where(Invoice.id == inv_id))).scalar_one()
            assert row.status == st


async def test_invoice_sweep_is_idempotent():
    """Running the sweep twice doesn't re-touch already-expired rows."""
    owner_id = await _seed_user(7003)

    expiry = int(settings.invoice_expiry_seconds)
    await _seed_invoice(
        owner_id,
        status=InvoiceStatus.pending,
        age_seconds=expiry + 600,
    )

    async with async_session() as session:
        first = await sweep_expired_invoices(session)
    async with async_session() as session:
        second = await sweep_expired_invoices(session)
    assert first == 1
    assert second == 0
