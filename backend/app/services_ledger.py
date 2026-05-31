from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CurrencyUsdRate, UserBalance, WalletLedgerEntry


def _d(value: Any) -> Decimal:
    return Decimal(str(value or 0))


async def latest_usd_rates(session: AsyncSession) -> dict[int, CurrencyUsdRate]:
    rows = (await session.execute(select(CurrencyUsdRate))).scalars().all()
    return {row.currency_id: row for row in rows}


async def latest_usd_rate(session: AsyncSession, currency_id: int) -> CurrencyUsdRate | None:
    return (
        await session.execute(
            select(CurrencyUsdRate).where(CurrencyUsdRate.currency_id == currency_id)
        )
    ).scalar_one_or_none()


def usd_estimate(amount: Decimal, rate: CurrencyUsdRate | None) -> Decimal | None:
    if rate is None:
        return None
    return amount * _d(rate.usd_rate)


def record_balance_ledger(
    session: AsyncSession,
    balance: UserBalance,
    *,
    before_amount: Decimal,
    before_locked: Decimal,
    event_type: str,
    source_type: str,
    source_id: int | None = None,
    provider: str | None = None,
    provider_event_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> WalletLedgerEntry | None:
    after_amount = _d(balance.amount)
    after_locked = _d(balance.locked)
    amount_delta = after_amount - before_amount
    locked_delta = after_locked - before_locked
    if amount_delta == 0 and locked_delta == 0:
        return None
    entry = WalletLedgerEntry(
        user_id=balance.user_id,
        currency_id=balance.currency_id,
        event_type=event_type,
        source_type=source_type,
        source_id=source_id,
        provider=provider,
        provider_event_id=provider_event_id,
        amount_before=before_amount,
        amount_delta=amount_delta,
        amount_after=after_amount,
        locked_before=before_locked,
        locked_delta=locked_delta,
        locked_after=after_locked,
        meta=meta,
    )
    session.add(entry)
    return entry


def record_synthetic_ledger(
    session: AsyncSession,
    *,
    user_id: int,
    currency_id: int,
    before_amount: Decimal,
    after_amount: Decimal,
    event_type: str,
    source_type: str,
    source_id: int | None = None,
    provider: str | None = None,
    provider_event_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> WalletLedgerEntry | None:
    amount_delta = after_amount - before_amount
    if amount_delta == 0:
        return None
    entry = WalletLedgerEntry(
        user_id=user_id,
        currency_id=currency_id,
        event_type=event_type,
        source_type=source_type,
        source_id=source_id,
        provider=provider,
        provider_event_id=provider_event_id,
        amount_before=before_amount,
        amount_delta=amount_delta,
        amount_after=after_amount,
        locked_before=Decimal("0"),
        locked_delta=Decimal("0"),
        locked_after=Decimal("0"),
        meta=meta,
    )
    session.add(entry)
    return entry
