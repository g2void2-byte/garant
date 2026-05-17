"""``/api/admin/treasury`` — commission accumulator + payouts.

Computed dynamically from completed deals minus successful treasury
withdrawals — there is no separate "treasury balance" column. This
avoids the bookkeeping consistency risk of double-writing on every
deal completion.

Endpoints:

* ``GET /api/admin/treasury`` — per-currency balances (accrued /
  withdrawn / available) + total withdrawal count.
* ``GET /api/admin/treasury/withdrawals`` — list of past withdrawals.
* ``POST /api/admin/treasury/withdraw`` — 2FA-gated payout to an
  external address. Requires ``confirm=true`` (double-confirm) and a
  valid TOTP code in the ``X-Totp-Code`` header.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, text

from ...admin_audit import log_admin_action
from ...admin_guard import TotpUser
from ...config import settings as app_settings_env
from ...cryptopay import CryptoPay, CryptoPayError
from ...deps import AdminUser, SessionDep
from ...models import Currency, Deal, DealStatus, TreasuryWithdrawal
from ...rate_limit import rate_limit
from ...schemas import (
    AdminTreasuryBalanceOut,
    AdminTreasuryOverviewOut,
    AdminTreasuryWithdrawIn,
    AdminTreasuryWithdrawOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/treasury",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin", limit=600, window=60))],
)


# Statuses where the platform commission has actually been collected.
# Per spec, commission is charged on every terminal deal (including
# refunds / cancellations / inactivity sweeps), so all terminal
# statuses contribute. Only the explicit admin "delete" path returns
# the full locked pot to the buyer — and a deleted deal is removed
# from this query because the row no longer exists.
_DONE_STATUSES = (
    DealStatus.completed,
    DealStatus.cancelled,
    DealStatus.cancelled_for_inactivity,
    DealStatus.resolved_for_buyer,
    DealStatus.resolved_for_seller,
)


async def _accrued_by_currency(session) -> dict[int, Decimal]:
    """Sum commission collected on every terminal deal."""
    rows = (
        await session.execute(
            select(Deal.currency_id, func.coalesce(func.sum(Deal.commission_amount), 0))
            .where(Deal.status.in_(_DONE_STATUSES))
            .group_by(Deal.currency_id)
        )
    ).all()
    return {cid: Decimal(str(amount or 0)) for cid, amount in rows if cid is not None}


# Statuses that count against the available balance. ``pending`` is
# included so a row in-flight (its CryptoBot transfer hasn't returned
# yet) can't be double-spent by another admin running concurrently.
# Only ``failed`` is excluded — those rows are explicit "no money
# left the platform" markers.
_OUTSTANDING_STATUSES = ("pending", "sent")


async def _withdrawn_by_currency(session) -> dict[int, Decimal]:
    """Sum of withdrawals that have already left or are leaving."""
    rows = (
        await session.execute(
            select(
                TreasuryWithdrawal.currency_id,
                func.coalesce(func.sum(TreasuryWithdrawal.amount), 0),
            )
            .where(TreasuryWithdrawal.status.in_(_OUTSTANDING_STATUSES))
            .group_by(TreasuryWithdrawal.currency_id)
        )
    ).all()
    return {cid: Decimal(str(amount or 0)) for cid, amount in rows}


# Namespace key for ``pg_advisory_xact_lock(key1, key2)``. Combining
# this constant with ``currency_id`` means concurrent treasury writes
# on the same currency serialize, while writes on different
# currencies (or on unrelated tables) don't contend.
_TREASURY_LOCK_NS = 0x74727377  # "trsw"


async def _lock_treasury(session, currency_id: int) -> None:
    """Take a per-currency Postgres advisory lock for this transaction.

    Released automatically when the transaction commits or rolls back.
    Prevents two concurrent ``POST /withdraw`` calls on the same
    currency from both passing the ``available`` guard.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :cid)"),
        {"ns": _TREASURY_LOCK_NS, "cid": int(currency_id)},
    )


@router.get("", response_model=AdminTreasuryOverviewOut)
async def treasury_overview(_admin: AdminUser, session: SessionDep):
    currencies = (
        (await session.execute(select(Currency).order_by(Currency.sort_order))).scalars().all()
    )
    accrued = await _accrued_by_currency(session)
    withdrawn = await _withdrawn_by_currency(session)
    total_count = (
        await session.execute(select(func.count()).select_from(TreasuryWithdrawal))
    ).scalar_one()

    balances = []
    for c in currencies:
        a = accrued.get(c.id, Decimal(0))
        w = withdrawn.get(c.id, Decimal(0))
        balances.append(
            AdminTreasuryBalanceOut(
                currency_id=c.id,
                currency_code=c.code,
                currency_name=c.name,
                decimals=c.decimals,
                accrued=a,
                withdrawn=w,
                available=a - w,
            )
        )
    return AdminTreasuryOverviewOut(balances=balances, total_withdrawals=int(total_count))


def _withdrawal_to_out(w: TreasuryWithdrawal, c: Currency | None) -> AdminTreasuryWithdrawOut:
    return AdminTreasuryWithdrawOut(
        id=w.id,
        actor_id=w.actor_id,
        currency_code=c.code if c else "",
        amount=w.amount,
        address=w.address,
        status=w.status,
        note=w.note,
        cryptobot_transfer_id=w.cryptobot_transfer_id,
        created_at=w.created_at,
    )


@router.get("/withdrawals", response_model=list[AdminTreasuryWithdrawOut])
async def list_treasury_withdrawals(
    _admin: AdminUser,
    session: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    rows = (
        await session.execute(
            select(TreasuryWithdrawal, Currency)
            .join(Currency, Currency.id == TreasuryWithdrawal.currency_id)
            .order_by(TreasuryWithdrawal.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [_withdrawal_to_out(w, c) for w, c in rows]


@router.post("/withdraw", response_model=AdminTreasuryWithdrawOut)
async def treasury_withdraw(
    body: AdminTreasuryWithdrawIn,
    admin: TotpUser,
    request: Request,
    session: SessionDep,
):
    """Withdraw accumulated commission to an external address.

    Guards:
      * 2FA via ``X-Totp-Code`` header.
      * ``confirm=true`` — explicit second click.
      * Per-currency advisory lock so two admins can't both pass the
        ``available`` guard concurrently.
      * Insert a ``pending`` row before the CryptoBot call so the
        spend_id is deterministic (``treas:{row.id}``). A retry from
        the admin produces a fresh row with its own id and its own
        spend_id; an in-flight crash leaves the ``pending`` row
        counted against ``available`` so the balance can't be
        double-spent until someone reconciles.
    """
    if not body.confirm:
        raise HTTPException(400, "Подтверждение не получено (confirm=false)")

    # Comment 48 (audit v9): without a configured CryptoBot token there is
    # no way to actually move funds, so the post-2026 codepath silently
    # marked the row ``status="sent"`` and committed — making the
    # accounting ledger believe a payout had been made while no transfer
    # ever happened. Reject early with 503 instead, before we touch the
    # DB or burn the per-currency advisory lock, so misconfigured envs
    # fail loudly rather than silently double-spending the treasury.
    token = app_settings_env.cryptobot_token or ""
    if not token or token.startswith("000"):
        raise HTTPException(503, "CryptoBot не настроен: вывод казны недоступен")

    currency = (
        await session.execute(select(Currency).where(Currency.code == body.currency_code))
    ).scalar_one_or_none()
    if currency is None:
        raise HTTPException(404, f"Валюта {body.currency_code} не найдена")

    await _lock_treasury(session, currency.id)

    accrued = await _accrued_by_currency(session)
    withdrawn = await _withdrawn_by_currency(session)
    available = accrued.get(currency.id, Decimal(0)) - withdrawn.get(currency.id, Decimal(0))
    if Decimal(str(body.amount)) > available:
        raise HTTPException(400, f"Недостаточно комиссии: доступно {available} {currency.code}")

    row = TreasuryWithdrawal(
        actor_id=admin.id,
        currency_id=currency.id,
        amount=body.amount,
        address=body.address,
        status="pending",
        note=body.note or "",
    )
    session.add(row)
    await session.flush()

    # Token presence was already validated at the top of the handler;
    # the inner ``startswith("000")`` guard would now be unreachable.
    transfer_id: int | None
    try:
        async with CryptoPay(
            app_settings_env.cryptobot_token,
            testnet=app_settings_env.cryptobot_testnet,
        ) as cp:
            tr = await cp.transfer(
                user_id=int(body.address) if body.address.isdigit() else admin.tg_user_id,
                asset=currency.code,
                amount=str(body.amount),
                spend_id=f"treas:{row.id}",
                comment="Garant treasury withdrawal",
            )
        transfer_id = tr.transfer_id
    except CryptoPayError as e:
        # V11-L-15 — structured-logging context so the JSON-logger
        # downstream surfaces actor/currency/amount as queryable
        # fields rather than substrings of the message.
        logger.error(
            "treasury withdraw failed: %s",
            e,
            extra={
                "event": "cryptobot.treasury_withdraw.failed",
                "treasury_withdrawal_id": row.id,
                "actor_id": admin.id,
                "currency": currency.code,
                "amount": str(body.amount),
            },
        )
        row.status = "failed"
        row.note = (row.note or "") + f"\nfailed: {e}"
        await log_admin_action(
            session,
            actor=admin,
            action="treasury.withdraw_failed",
            target_type="treasury",
            target_id=row.id,
            reason=body.note,
            payload={
                "currency": currency.code,
                "amount": str(body.amount),
                "address": body.address,
                "error": str(e),
            },
            request=request,
        )
        await session.commit()
        raise HTTPException(502, f"Ошибка CryptoBot: {e}") from e

    row.status = "sent"
    row.cryptobot_transfer_id = str(transfer_id) if transfer_id is not None else None

    await log_admin_action(
        session,
        actor=admin,
        action="treasury.withdraw",
        target_type="treasury",
        target_id=row.id,
        reason=body.note,
        payload={
            "currency": currency.code,
            "amount": str(body.amount),
            "address": body.address,
            "cryptobot_transfer_id": transfer_id,
        },
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return _withdrawal_to_out(row, currency)
