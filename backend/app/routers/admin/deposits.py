"""``/api/admin/deposits`` — deposit-queue inspection + manual operations.

Endpoints:

* ``GET /api/admin/deposits`` — paginated list of ``wallet_deposits``,
  with status / currency / user filters.
* ``POST /api/admin/deposits/:id/mark-paid`` — manually credit a
  deposit that the CryptoBot webhook missed (idempotent; subsequent
  calls return the same row unchanged).
* ``POST /api/admin/deposits/:id/refund`` — reverse a credited deposit
  by deducting the amount from the user's available balance.

Both mutations write a single audit row inside the same transaction as
the balance change.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select

from ... import notifier
from ...admin_audit import log_admin_action
from ...deps import AdminUser, SessionDep
from ...models import (
    Currency,
    NotificationType,
    User,
    UserBalance,
    WalletDeposit,
    WalletDepositStatus,
)
from ...rate_limit import rate_limit
from ...schemas import AdminDepositListOut, AdminDepositOut, AdminReasonIn
from ...services_wallet import get_or_create_balance

router = APIRouter(
    prefix="/api/admin/deposits",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin", limit=600, window=60))],
)


def _to_out(d: WalletDeposit, c: Currency | None, u: User | None) -> AdminDepositOut:
    return AdminDepositOut(
        id=d.id,
        user_id=d.user_id,
        username=u.username if u else None,
        display_name=u.display_name if u else "",
        currency_code=c.code if c else "",
        amount=float(d.amount),
        status=d.status.value,
        provider_invoice_id=d.provider_invoice_id,
        pay_url=d.pay_url,
        created_at=d.created_at,
        paid_at=d.paid_at,
    )


@router.get("", response_model=AdminDepositListOut)
async def list_deposits(
    _admin: AdminUser,
    session: SessionDep,
    status: str | None = Query(None),
    currency: str | None = Query(None),
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    stmt = (
        select(WalletDeposit, Currency, User)
        .join(Currency, Currency.id == WalletDeposit.currency_id)
        .join(User, User.id == WalletDeposit.user_id)
    )
    if status:
        try:
            stmt = stmt.where(WalletDeposit.status == WalletDepositStatus(status))
        except ValueError:
            raise HTTPException(422, f"Неизвестный статус: {status}")
    if currency:
        stmt = stmt.where(Currency.code == currency.upper())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.username.ilike(like), User.display_name.ilike(like)))

    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(WalletDeposit.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return AdminDepositListOut(
        items=[_to_out(d, c, u) for d, c, u in rows],
        total=int(total),
        page=page,
        page_size=page_size,
    )


@router.post("/{deposit_id}/mark-paid", response_model=AdminDepositOut)
async def mark_paid(
    deposit_id: int,
    body: AdminReasonIn,
    admin: AdminUser,
    session: SessionDep,
    request: Request,
):
    d = (
        await session.execute(
            select(WalletDeposit).where(WalletDeposit.id == deposit_id).with_for_update()
        )
    ).scalar_one_or_none()
    if d is None:
        raise HTTPException(404, "Депозит не найден")

    if d.status == WalletDepositStatus.paid:
        # Idempotent: don't credit twice, return current state.
        c = await session.get(Currency, d.currency_id)
        u = await session.get(User, d.user_id)
        return _to_out(d, c, u)

    currency = await session.get(Currency, d.currency_id)
    if currency is None:
        raise HTTPException(500, "Валюта не найдена")

    bal = await get_or_create_balance(session, d.user_id, d.currency_id)
    bal.amount = float(Decimal(str(bal.amount)) + Decimal(str(d.amount)))
    d.status = WalletDepositStatus.paid
    d.paid_at = datetime.utcnow()

    await notifier.push(
        session,
        d.user_id,
        NotificationType.deposits,
        "Пополнение зачислено",
        f"+{d.amount} {currency.code} зачислены администратором",
        {"deposit_id": d.id, "currency": currency.code},
    )

    await log_admin_action(
        session,
        actor=admin,
        action="deposit.mark_paid",
        target_type="deposit",
        target_id=d.id,
        reason=body.reason,
        payload={
            "user_id": d.user_id,
            "currency": currency.code,
            "amount": float(d.amount),
        },
        request=request,
    )
    await session.commit()
    await session.refresh(d)

    u = await session.get(User, d.user_id)
    return _to_out(d, currency, u)


@router.post("/{deposit_id}/refund", response_model=AdminDepositOut)
async def refund_deposit(
    deposit_id: int,
    body: AdminReasonIn,
    admin: AdminUser,
    session: SessionDep,
    request: Request,
):
    """Reverse a paid deposit by debiting the user's spendable balance."""
    d = (
        await session.execute(
            select(WalletDeposit).where(WalletDeposit.id == deposit_id).with_for_update()
        )
    ).scalar_one_or_none()
    if d is None:
        raise HTTPException(404, "Депозит не найден")

    if d.status != WalletDepositStatus.paid:
        raise HTTPException(400, "Можно вернуть только зачисленный депозит")

    currency = await session.get(Currency, d.currency_id)
    if currency is None:
        raise HTTPException(500, "Валюта не найдена")

    bal = (
        await session.execute(
            select(UserBalance)
            .where(
                UserBalance.user_id == d.user_id,
                UserBalance.currency_id == d.currency_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if bal is None or Decimal(str(bal.amount)) < Decimal(str(d.amount)):
        raise HTTPException(400, "Недостаточно средств у пользователя для возврата")

    bal.amount = float(Decimal(str(bal.amount)) - Decimal(str(d.amount)))
    d.status = WalletDepositStatus.expired
    d.paid_at = None

    await notifier.push(
        session,
        d.user_id,
        NotificationType.deposits,
        "Депозит возвращён",
        f"−{d.amount} {currency.code} списаны (возврат)",
        {"deposit_id": d.id, "currency": currency.code},
    )

    await log_admin_action(
        session,
        actor=admin,
        action="deposit.refund",
        target_type="deposit",
        target_id=d.id,
        reason=body.reason,
        payload={
            "user_id": d.user_id,
            "currency": currency.code,
            "amount": float(d.amount),
        },
        request=request,
    )
    await session.commit()
    await session.refresh(d)

    u = await session.get(User, d.user_id)
    return _to_out(d, currency, u)
