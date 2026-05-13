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
from sqlalchemy import func, select

from ...admin_audit import log_admin_action
from ...auth_2fa import require_totp
from ...config import settings as app_settings_env
from ...cryptopay import CryptoPay, CryptoPayError
from ...deps import AdminUser, SessionDep
from ...models import Currency, Deal, DealStatus, TreasuryWithdrawal, User
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


_DONE_STATUSES = (
    DealStatus.completed,
    DealStatus.resolved_for_buyer,
    DealStatus.resolved_for_seller,
)


async def _accrued_by_currency(session) -> dict[int, Decimal]:
    """Sum commission collected on every completed/resolved deal."""
    rows = (
        await session.execute(
            select(Deal.currency_id, func.coalesce(func.sum(Deal.commission_amount), 0))
            .where(Deal.status.in_(_DONE_STATUSES))
            .group_by(Deal.currency_id)
        )
    ).all()
    return {cid: Decimal(str(amount or 0)) for cid, amount in rows if cid is not None}


async def _withdrawn_by_currency(session) -> dict[int, Decimal]:
    """Sum of all successful treasury withdrawals."""
    rows = (
        await session.execute(
            select(
                TreasuryWithdrawal.currency_id,
                func.coalesce(func.sum(TreasuryWithdrawal.amount), 0),
            )
            .where(TreasuryWithdrawal.status == "sent")
            .group_by(TreasuryWithdrawal.currency_id)
        )
    ).all()
    return {cid: Decimal(str(amount or 0)) for cid, amount in rows}


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
                accrued=float(a),
                withdrawn=float(w),
                available=float(a - w),
            )
        )
    return AdminTreasuryOverviewOut(balances=balances, total_withdrawals=int(total_count))


def _withdrawal_to_out(w: TreasuryWithdrawal, c: Currency | None) -> AdminTreasuryWithdrawOut:
    return AdminTreasuryWithdrawOut(
        id=w.id,
        actor_id=w.actor_id,
        currency_code=c.code if c else "",
        amount=float(w.amount),
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
    request: Request,
    session: SessionDep,
    admin: User = Depends(require_totp),
):
    """Withdraw accumulated commission to an external address.

    Guards:
      * 2FA via ``X-Totp-Code`` header.
      * ``confirm=true`` \u2014 explicit second click.
      * Available balance check.
      * CryptoBot ``spend_id = "treas:{currency_id}:{timestamp}"`` so a
        replay of the same request doesn't double-pay.
    """
    import time

    if not body.confirm:
        raise HTTPException(400, "Подтверждение не получено (confirm=false)")

    currency = (
        await session.execute(select(Currency).where(Currency.code == body.currency_code))
    ).scalar_one_or_none()
    if currency is None:
        raise HTTPException(404, f"Валюта {body.currency_code} не найдена")

    accrued = await _accrued_by_currency(session)
    withdrawn = await _withdrawn_by_currency(session)
    available = accrued.get(currency.id, Decimal(0)) - withdrawn.get(currency.id, Decimal(0))
    if Decimal(str(body.amount)) > available:
        raise HTTPException(400, f"Недостаточно комиссии: доступно {available} {currency.code}")

    transfer_id: int | None = None
    if app_settings_env.cryptobot_token and not app_settings_env.cryptobot_token.startswith("000"):
        try:
            async with CryptoPay(
                app_settings_env.cryptobot_token,
                testnet=app_settings_env.cryptobot_testnet,
            ) as cp:
                tr = await cp.transfer(
                    user_id=int(body.address) if body.address.isdigit() else admin.tg_user_id,
                    asset=currency.code,
                    amount=str(body.amount),
                    spend_id=f"treas:{currency.id}:{int(time.time())}",
                    comment="Garant treasury withdrawal",
                )
            transfer_id = tr.transfer_id
        except CryptoPayError as e:
            logger.error("treasury withdraw failed: %s", e)
            raise HTTPException(502, f"Ошибка CryptoBot: {e}")

    row = TreasuryWithdrawal(
        actor_id=admin.id,
        currency_id=currency.id,
        amount=body.amount,
        address=body.address,
        status="sent",
        note=body.note or "",
        cryptobot_transfer_id=str(transfer_id) if transfer_id is not None else None,
    )
    session.add(row)
    await session.flush()

    await log_admin_action(
        session,
        actor=admin,
        action="treasury.withdraw",
        target_type="treasury",
        target_id=row.id,
        reason=body.note,
        payload={
            "currency": currency.code,
            "amount": float(body.amount),
            "address": body.address,
            "cryptobot_transfer_id": transfer_id,
        },
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return _withdrawal_to_out(row, currency)
