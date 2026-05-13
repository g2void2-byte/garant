"""Wallet endpoints.

Currencies are listed by ``GET /api/wallet/currencies``; per-user balances
by ``GET /api/wallet/balances``. Deposits go through CryptoBot, withdrawals
are admin-processed (see ``services_wallet``).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..deps import CurrentUser, PinUser, SessionDep
from ..models import (
    Currency,
    WalletDeposit,
    WalletWithdrawal,
    WalletWithdrawStatus,
)
from ..rate_limit import RLWithdrawal
from ..schemas import (
    CurrencyOut,
    WalletAdminWithdrawDecision,
    WalletBalanceOut,
    WalletDepositCreateReq,
    WalletDepositOut,
    WalletWithdrawalOut,
    WalletWithdrawCreateReq,
)
from ..services_wallet import (
    create_deposit_invoice,
    create_withdrawal,
    decide_withdrawal,
    list_balances,
    poll_deposit_status,
)

router = APIRouter(prefix="/api/wallet", tags=["wallet"])


def _currency_dto(c: Currency) -> CurrencyOut:
    return CurrencyOut(
        id=c.id,
        code=c.code,
        name=c.name,
        network=c.network,
        icon_url=c.icon_url,
        decimals=c.decimals,
        min_deposit=float(c.min_deposit),
        min_withdraw=float(c.min_withdraw),
    )


def _deposit_dto(d: WalletDeposit, c: Currency) -> WalletDepositOut:
    return WalletDepositOut(
        id=d.id,
        currency=_currency_dto(c),
        amount=float(d.amount),
        status=d.status.value,
        pay_url=d.pay_url,
        invoice_id=d.provider_invoice_id,
        created_at=d.created_at,
        paid_at=d.paid_at,
    )


def _withdrawal_dto(w: WalletWithdrawal, c: Currency) -> WalletWithdrawalOut:
    return WalletWithdrawalOut(
        id=w.id,
        currency=_currency_dto(c),
        amount=float(w.amount),
        address=w.address,
        status=w.status.value,
        locked_until=w.locked_until,
        admin_note=w.admin_note,
        created_at=w.created_at,
        processed_at=w.processed_at,
    )


# ── Currencies ─────────────────────────────────────────


@router.get("/currencies", response_model=list[CurrencyOut])
async def list_currencies(session: SessionDep):
    rows = (
        (
            await session.execute(
                select(Currency).where(Currency.is_active.is_(True)).order_by(Currency.sort_order)
            )
        )
        .scalars()
        .all()
    )
    return [_currency_dto(c) for c in rows]


# ── Balances ───────────────────────────────────────────


@router.get("/balances", response_model=list[WalletBalanceOut])
async def get_balances(user: CurrentUser, session: SessionDep):
    rows = await list_balances(session, user.id)
    return [
        WalletBalanceOut(
            currency=_currency_dto(c),
            amount=float(b.amount) if b else 0.0,
            locked=float(b.locked) if b else 0.0,
            total=(float(b.amount) + float(b.locked)) if b else 0.0,
            updated_at=b.updated_at if b else None,
        )
        for c, b in rows
    ]


# ── Deposits ───────────────────────────────────────────


@router.post("/deposits", response_model=WalletDepositOut)
async def create_deposit(body: WalletDepositCreateReq, user: CurrentUser, session: SessionDep):
    deposit = await create_deposit_invoice(session, user, body.currency_code, body.amount)
    currency = await session.get(Currency, deposit.currency_id)
    if currency is None:
        raise HTTPException(500, "currency vanished")
    return _deposit_dto(deposit, currency)


@router.get("/deposits", response_model=list[WalletDepositOut])
async def list_user_deposits(user: CurrentUser, session: SessionDep):
    rows = (
        await session.execute(
            select(WalletDeposit, Currency)
            .join(Currency, Currency.id == WalletDeposit.currency_id)
            .where(WalletDeposit.user_id == user.id)
            .order_by(WalletDeposit.created_at.desc())
            .limit(100)
        )
    ).all()
    return [_deposit_dto(d, c) for d, c in rows]


@router.get("/deposits/{deposit_id}", response_model=WalletDepositOut)
async def get_deposit(deposit_id: int, user: CurrentUser, session: SessionDep):
    deposit = await session.get(WalletDeposit, deposit_id)
    if deposit is None or deposit.user_id != user.id:
        raise HTTPException(404, "Депозит не найден")
    deposit = await poll_deposit_status(session, deposit)
    currency = await session.get(Currency, deposit.currency_id)
    if currency is None:
        raise HTTPException(500, "currency vanished")
    return _deposit_dto(deposit, currency)


# ── Withdrawals ────────────────────────────────────────


@router.post("/withdrawals", response_model=WalletWithdrawalOut)
async def create_user_withdrawal(
    body: WalletWithdrawCreateReq,
    user: PinUser,
    session: SessionDep,
    _rl: RLWithdrawal,
):
    w = await create_withdrawal(session, user, body.currency_code, body.amount, body.address)
    currency = await session.get(Currency, w.currency_id)
    if currency is None:
        raise HTTPException(500, "currency vanished")
    return _withdrawal_dto(w, currency)


@router.get("/withdrawals", response_model=list[WalletWithdrawalOut])
async def list_user_withdrawals(user: CurrentUser, session: SessionDep):
    rows = (
        await session.execute(
            select(WalletWithdrawal, Currency)
            .join(Currency, Currency.id == WalletWithdrawal.currency_id)
            .where(WalletWithdrawal.user_id == user.id)
            .order_by(WalletWithdrawal.created_at.desc())
            .limit(100)
        )
    ).all()
    return [_withdrawal_dto(w, c) for w, c in rows]


# ── Admin: withdrawal queue ────────────────────────────


@router.get("/admin/withdrawals", response_model=list[WalletWithdrawalOut])
async def admin_list_withdrawals(user: CurrentUser, session: SessionDep):
    if not user.is_admin:
        raise HTTPException(403, "Доступ только для администратора")
    rows = (
        await session.execute(
            select(WalletWithdrawal, Currency)
            .join(Currency, Currency.id == WalletWithdrawal.currency_id)
            .where(
                WalletWithdrawal.status.in_(
                    [WalletWithdrawStatus.pending, WalletWithdrawStatus.approved]
                )
            )
            .order_by(WalletWithdrawal.created_at.asc())
        )
    ).all()
    return [_withdrawal_dto(w, c) for w, c in rows]


@router.post("/admin/withdrawals/{withdrawal_id}", response_model=WalletWithdrawalOut)
async def admin_decide_withdrawal(
    withdrawal_id: int,
    body: WalletAdminWithdrawDecision,
    user: CurrentUser,
    session: SessionDep,
):
    w = await session.get(WalletWithdrawal, withdrawal_id)
    if w is None:
        raise HTTPException(404, "Заявка не найдена")
    w = await decide_withdrawal(session, user, w, body.action, body.note)
    currency = await session.get(Currency, w.currency_id)
    if currency is None:
        raise HTTPException(500, "currency vanished")
    return _withdrawal_dto(w, currency)
