"""Business logic for the multi-currency wallet.

Funds split between ``UserBalance.amount`` (spendable) and
``UserBalance.locked`` (held while a withdrawal is awaiting admin
review or during the cool-down window).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import notifier
from .config import settings
from .models import (
    Currency,
    NotificationType,
    User,
    UserBalance,
    WalletDeposit,
    WalletDepositStatus,
    WalletWithdrawal,
    WalletWithdrawStatus,
)

logger = logging.getLogger(__name__)


WITHDRAW_LOCK_HOURS = 24


async def get_currency_by_code(session: AsyncSession, code: str) -> Currency:
    result = await session.execute(
        select(Currency).where(Currency.code == code.upper(), Currency.is_active.is_(True))
    )
    cur = result.scalar_one_or_none()
    if cur is None:
        raise HTTPException(404, f"Валюта {code} не поддерживается")
    return cur


async def get_or_create_balance(
    session: AsyncSession, user_id: int, currency_id: int
) -> UserBalance:
    result = await session.execute(
        select(UserBalance).where(
            UserBalance.user_id == user_id, UserBalance.currency_id == currency_id
        )
    )
    bal = result.scalar_one_or_none()
    if bal is None:
        bal = UserBalance(user_id=user_id, currency_id=currency_id, amount=0, locked=0)
        session.add(bal)
        await session.flush()
    return bal


async def list_balances(session: AsyncSession, user_id: int) -> list[tuple[Currency, UserBalance | None]]:
    """Return every active currency with the user's balance row (or None)."""
    currencies = (
        await session.execute(
            select(Currency).where(Currency.is_active.is_(True)).order_by(Currency.sort_order)
        )
    ).scalars().all()
    balances = (
        await session.execute(select(UserBalance).where(UserBalance.user_id == user_id))
    ).scalars().all()
    by_currency = {b.currency_id: b for b in balances}
    return [(c, by_currency.get(c.id)) for c in currencies]


# ── Deposits ───────────────────────────────────────────


async def create_deposit_invoice(
    session: AsyncSession, user: User, currency_code: str, amount: float
) -> WalletDeposit:
    if not settings.cryptobot_token or settings.cryptobot_token.startswith("000"):
        raise HTTPException(502, "CryptoBot не настроен")

    currency = await get_currency_by_code(session, currency_code)
    if amount < float(currency.min_deposit):
        raise HTTPException(
            400, f"Минимальная сумма пополнения: {currency.min_deposit} {currency.code}"
        )

    try:
        from AsyncPayments.cryptoBot import CryptoBot

        crypto = CryptoBot(settings.cryptobot_token)
        invoice = await crypto.create_invoice(asset=currency.code, amount=amount)
    except Exception as e:
        logger.error("CryptoBot invoice error: %s", e)
        raise HTTPException(502, f"Ошибка CryptoBot: {e}")

    deposit = WalletDeposit(
        user_id=user.id,
        currency_id=currency.id,
        amount=amount,
        provider_invoice_id=str(invoice.invoice_id),
        pay_url=invoice.pay_url,
        status=WalletDepositStatus.pending,
    )
    session.add(deposit)
    await session.commit()
    await session.refresh(deposit)
    return deposit


async def credit_deposit(session: AsyncSession, deposit: WalletDeposit) -> WalletDeposit:
    """Mark a deposit ``paid`` and credit the user balance. Idempotent."""
    if deposit.status == WalletDepositStatus.paid:
        return deposit

    bal = await get_or_create_balance(session, deposit.user_id, deposit.currency_id)
    bal.amount = float(bal.amount) + float(deposit.amount)
    deposit.status = WalletDepositStatus.paid
    deposit.paid_at = datetime.utcnow()
    await session.commit()
    await session.refresh(deposit)

    currency = await session.get(Currency, deposit.currency_id)
    if currency:
        await notifier.push(
            session,
            deposit.user_id,
            NotificationType.deposits,
            "Пополнение зачислено",
            f"+{deposit.amount} {currency.code} зачислены на ваш баланс",
            {"deposit_id": deposit.id, "currency": currency.code},
        )

    return deposit


async def poll_deposit_status(session: AsyncSession, deposit: WalletDeposit) -> WalletDeposit:
    """Refresh a pending deposit's status from CryptoBot. Idempotent."""
    if deposit.status != WalletDepositStatus.pending:
        return deposit
    if not settings.cryptobot_token:
        return deposit
    try:
        from AsyncPayments.cryptoBot import CryptoBot

        crypto = CryptoBot(settings.cryptobot_token)
        rows = await crypto.get_invoices(invoice_ids=[int(deposit.provider_invoice_id)])
    except Exception as e:
        logger.warning("CryptoBot poll error: %s", e)
        return deposit

    if not rows:
        return deposit
    row = rows[0]
    if row.status == "paid":
        return await credit_deposit(session, deposit)
    if row.status == "expired":
        deposit.status = WalletDepositStatus.expired
        await session.commit()
        await session.refresh(deposit)
    return deposit


# ── Withdrawals ────────────────────────────────────────


async def create_withdrawal(
    session: AsyncSession, user: User, currency_code: str, amount: float, address: str
) -> WalletWithdrawal:
    currency = await get_currency_by_code(session, currency_code)
    if amount < float(currency.min_withdraw):
        raise HTTPException(
            400, f"Минимальная сумма вывода: {currency.min_withdraw} {currency.code}"
        )

    bal = await get_or_create_balance(session, user.id, currency.id)
    if float(bal.amount) < amount:
        raise HTTPException(400, "Недостаточно средств")

    bal.amount = float(bal.amount) - amount
    bal.locked = float(bal.locked) + amount

    withdrawal = WalletWithdrawal(
        user_id=user.id,
        currency_id=currency.id,
        amount=amount,
        address=address,
        status=WalletWithdrawStatus.pending,
        locked_until=datetime.utcnow() + timedelta(hours=WITHDRAW_LOCK_HOURS),
    )
    session.add(withdrawal)
    await session.commit()
    await session.refresh(withdrawal)

    # Notify admins
    admins = (
        await session.execute(select(User).where(User.is_admin.is_(True)))
    ).scalars().all()
    for admin in admins:
        await notifier.push(
            session,
            admin.id,
            NotificationType.system,
            "Заявка на вывод",
            f"@{user.username or user.tg_user_id}: {amount} {currency.code} → {address[:12]}…",
            {"withdrawal_id": withdrawal.id},
        )

    return withdrawal


async def decide_withdrawal(
    session: AsyncSession,
    admin: User,
    withdrawal: WalletWithdrawal,
    action: str,
    note: str = "",
) -> WalletWithdrawal:
    if not admin.is_admin:
        raise HTTPException(403, "Только администратор может обрабатывать заявки")
    if withdrawal.status not in (WalletWithdrawStatus.pending, WalletWithdrawStatus.approved):
        raise HTTPException(409, "Заявка уже обработана")

    bal = await get_or_create_balance(session, withdrawal.user_id, withdrawal.currency_id)
    currency = await session.get(Currency, withdrawal.currency_id)

    if action == "approve":
        withdrawal.status = WalletWithdrawStatus.approved
        withdrawal.admin_note = note
    elif action == "reject":
        bal.locked = max(0.0, float(bal.locked) - float(withdrawal.amount))
        bal.amount = float(bal.amount) + float(withdrawal.amount)
        withdrawal.status = WalletWithdrawStatus.rejected
        withdrawal.admin_note = note
        withdrawal.processed_at = datetime.utcnow()
        if currency:
            await notifier.push(
                session,
                withdrawal.user_id,
                NotificationType.deposits,
                "Заявка на вывод отклонена",
                f"{withdrawal.amount} {currency.code} возвращены на баланс. {note}".strip(),
                {"withdrawal_id": withdrawal.id},
            )
    elif action == "send":
        bal.locked = max(0.0, float(bal.locked) - float(withdrawal.amount))
        withdrawal.status = WalletWithdrawStatus.sent
        withdrawal.admin_note = note
        withdrawal.processed_at = datetime.utcnow()
        if currency:
            await notifier.push(
                session,
                withdrawal.user_id,
                NotificationType.deposits,
                "Вывод выполнен",
                f"-{withdrawal.amount} {currency.code} отправлены на {withdrawal.address}",
                {"withdrawal_id": withdrawal.id},
            )
    else:
        raise HTTPException(400, "Неизвестное действие")

    await session.commit()
    await session.refresh(withdrawal)
    return withdrawal
