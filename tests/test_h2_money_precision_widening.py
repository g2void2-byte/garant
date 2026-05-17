"""H-2 regression — every money column on the per-currency ledger
keeps the full ``Numeric(28,8)`` precision.

Pre-fix every column below was declared ``Numeric(18,8)`` while
``Deal.amount`` already used ``Numeric(28,8)``. A value whose integer
part exceeded 10¹⁰ (realistic for USDT / USDC at 8 fractional digits
and for fiat-like assets without a satoshi-scale decimals split)
would silently truncate on write — Postgres raises ``numeric field
overflow`` only when the integer part is too wide for ``precision -
scale = 10`` digits, but a 11-digit integer part would already be on
the rejection boundary, and any safe-side rounding inside the driver
would happen before we ever saw the row.

The widening migration (``9c3a4d2e1f08``) brings every
per-currency money column up to ``Numeric(28,8)``: ``UserBalance``
(``amount`` / ``locked``), ``WalletDeposit.amount``,
``WalletWithdrawal.amount``, ``TreasuryWithdrawal.amount`` and
``Currency.min_deposit`` / ``min_withdraw``. This file pins the new
contract: a value that previously *would* have overflowed
``Numeric(18,8)`` now round-trips byte-for-byte.

The check is intentionally column-level (raw SQLAlchemy / ORM, no
HTTP routing) because the precision contract is a property of the DB
schema rather than any specific endpoint. We use the ORM so the
``Mapped[float] = mapped_column(Numeric(28,8), ...)`` declarations
participate in the round-trip — a future regression that reverts a
column to ``Numeric(18,8)`` would surface here as a
``numeric field overflow`` from asyncpg.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import (
    Currency,
    InvoiceProvider,
    TreasuryWithdrawal,
    User,
    UserBalance,
    WalletDeposit,
    WalletDepositStatus,
    WalletWithdrawal,
    WalletWithdrawStatus,
)

# 12-digit integer part * 8 fractional digits = 20 significant
# digits. Pre-fix this would have failed ``Numeric(18,8)``'s
# precision check (10 digit max integer part). Post-fix it fits
# inside ``Numeric(28,8)`` with eight digits to spare.
_BIG = Decimal("123456789012.34567890")
# 18-digit integer part — at the upper edge of ``Numeric(28,8)``
# (28 - 8 = 20 digit max integer part). Used to assert the precision
# headroom is real, not just nominally widened.
_HUGE = Decimal("123456789012345678.12345678")


@pytest.mark.asyncio
async def test_user_balance_amount_and_locked_round_trip_above_1e10():
    """``UserBalance`` columns hold a 12-digit-integer-part Decimal
    without truncation. Pre-H-2 the row would have failed ``Numeric
    (18,8)``'s width check; now the read-back matches byte-for-byte.
    """
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        user = User(tg_user_id=49001, username="h2_balance", display_name="h2")
        session.add(user)
        await session.flush()

        bal = UserBalance(
            user_id=user.id,
            currency_id=usdt.id,
            amount=_BIG,
            locked=_HUGE,
        )
        session.add(bal)
        await session.commit()

        fresh = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == user.id, UserBalance.currency_id == usdt.id
                )
            )
        ).scalar_one()

    assert Decimal(str(fresh.amount)) == _BIG
    assert Decimal(str(fresh.locked)) == _HUGE


@pytest.mark.asyncio
async def test_wallet_deposit_amount_round_trips_above_1e10():
    """A ``WalletDeposit`` row at the 10¹² scale is stored exactly."""
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        user = User(tg_user_id=49002, username="h2_deposit", display_name="h2d")
        session.add(user)
        await session.flush()

        dep = WalletDeposit(
            user_id=user.id,
            currency_id=usdt.id,
            amount=_BIG,
            provider=InvoiceProvider.cryptobot,
            provider_invoice_id="h2-test-deposit",
            pay_url="",
            status=WalletDepositStatus.pending,
        )
        session.add(dep)
        await session.commit()

        fresh = (
            await session.execute(
                select(WalletDeposit).where(WalletDeposit.provider_invoice_id == "h2-test-deposit")
            )
        ).scalar_one()

    assert Decimal(str(fresh.amount)) == _BIG


@pytest.mark.asyncio
async def test_wallet_withdrawal_amount_round_trips_above_1e10():
    """A ``WalletWithdrawal`` row at the 10¹⁸ scale is stored exactly."""
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        user = User(tg_user_id=49003, username="h2_withdraw", display_name="h2w")
        session.add(user)
        await session.flush()

        wd = WalletWithdrawal(
            user_id=user.id,
            currency_id=usdt.id,
            amount=_HUGE,
            address="UQAh2withdrawh2",
            status=WalletWithdrawStatus.pending,
        )
        session.add(wd)
        await session.commit()

        fresh = (
            await session.execute(
                select(WalletWithdrawal).where(WalletWithdrawal.user_id == user.id)
            )
        ).scalar_one()

    assert Decimal(str(fresh.amount)) == _HUGE


@pytest.mark.asyncio
async def test_treasury_withdrawal_amount_round_trips_above_1e10():
    """A ``TreasuryWithdrawal`` row at the 10¹² scale is stored exactly."""
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        actor = User(tg_user_id=49004, username="h2_treasury", display_name="h2t")
        session.add(actor)
        await session.flush()

        tw = TreasuryWithdrawal(
            actor_id=actor.id,
            currency_id=usdt.id,
            amount=_BIG,
            address="UQAh2treasury",
            status="sent",
        )
        session.add(tw)
        await session.commit()

        fresh = (
            await session.execute(
                select(TreasuryWithdrawal).where(TreasuryWithdrawal.actor_id == actor.id)
            )
        ).scalar_one()

    assert Decimal(str(fresh.amount)) == _BIG


@pytest.mark.asyncio
async def test_currency_min_deposit_and_min_withdraw_round_trip_above_1e10():
    """``Currency.min_deposit`` / ``min_withdraw`` carry the full
    ``Numeric(28,8)`` domain — important for fiat-shaped assets where
    a ``min_deposit`` is denominated in whole units, not satoshi.
    """
    async with async_session() as session:
        c = Currency(
            code="H2C",
            name="H-2 contract currency",
            network="",
            icon_url="",
            decimals=8,
            min_deposit=_BIG,
            min_withdraw=_HUGE,
            is_active=True,
            sort_order=999,
        )
        session.add(c)
        await session.commit()

        fresh = (await session.execute(select(Currency).where(Currency.code == "H2C"))).scalar_one()

    assert Decimal(str(fresh.min_deposit)) == _BIG
    assert Decimal(str(fresh.min_withdraw)) == _HUGE
