"""Business logic for the multi-currency wallet.

Funds split between ``UserBalance.amount`` (spendable) and
``UserBalance.locked`` (held while a withdrawal is awaiting admin
review or during the cool-down window).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import notifier
from .config import settings
from .cryptopay import CryptoPay, CryptoPayError
from .models import (
    AppSettings,
    Currency,
    NotificationType,
    User,
    UserBalance,
    WalletDeposit,
    WalletDepositStatus,
    WalletWithdrawal,
    WalletWithdrawStatus,
)
from .time_utils import utcnow

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


async def lock_user_balance(session: AsyncSession, user_id: int, currency_id: int) -> UserBalance:
    """Return the user's balance row with a ``FOR UPDATE`` row lock held.

    Used by money-moving flows (withdrawal, deal creation) where two
    concurrent requests must not both pass an ``amount >= price``
    check. A newly inserted row is implicitly locked by the inserting
    transaction, so the missing-row branch needs no extra select.
    """
    bal = (
        await session.execute(
            select(UserBalance)
            .where(
                UserBalance.user_id == user_id,
                UserBalance.currency_id == currency_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if bal is None:
        bal = UserBalance(user_id=user_id, currency_id=currency_id, amount=0, locked=0)
        session.add(bal)
        await session.flush()
    return bal


async def list_balances(
    session: AsyncSession, user_id: int
) -> list[tuple[Currency, UserBalance | None]]:
    """Return every active currency with the user's balance row (or None)."""
    currencies = (
        (
            await session.execute(
                select(Currency).where(Currency.is_active.is_(True)).order_by(Currency.sort_order)
            )
        )
        .scalars()
        .all()
    )
    balances = (
        (await session.execute(select(UserBalance).where(UserBalance.user_id == user_id)))
        .scalars()
        .all()
    )
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
        async with CryptoPay(
            settings.cryptobot_token, testnet=settings.cryptobot_testnet
        ) as crypto:
            invoice = await crypto.create_invoice(asset=currency.code, amount=amount)
    except CryptoPayError as e:
        logger.error("CryptoBot invoice error: %s", e)
        raise HTTPException(502, f"Ошибка CryptoBot: {e}")

    pay_url = (
        invoice.mini_app_invoice_url
        or invoice.bot_invoice_url
        or invoice.pay_url
        or invoice.web_app_invoice_url
        or ""
    )
    deposit = WalletDeposit(
        user_id=user.id,
        currency_id=currency.id,
        amount=amount,
        provider_invoice_id=str(invoice.invoice_id),
        pay_url=pay_url,
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
    # See M5 in services_deals._debit for why this stays Decimal end-
    # to-end instead of round-tripping through ``float``.
    bal.amount = Decimal(str(bal.amount)) + Decimal(str(deposit.amount))
    deposit.status = WalletDepositStatus.paid
    deposit.paid_at = utcnow()

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

    await session.commit()
    await session.refresh(deposit)

    return deposit


async def sweep_expired_deposits(session: AsyncSession) -> int:
    """Mark stale ``pending`` deposits as ``expired``.

    M-6 — pre-fix, a ``WalletDeposit(status=pending)`` row created when
    the user clicked "deposit" but never paid sat in the admin queue
    forever. CryptoBot stops issuing webhooks for the invoice once it
    has expired on their side (default 24h), so the row had no
    independent path to a terminal state. This sweep closes the loop:
    every ``wallet_deposit_sweep_seconds`` the loop in
    :mod:`backend.app.main` runs us and we flip any
    ``pending`` row older than ``wallet_deposit_expiry_seconds`` to
    ``expired``. No balance is credited; the user can always create
    a fresh deposit if they actually wanted to pay.

    Uses ``with_for_update(skip_locked=True)`` so a concurrent sweep
    in a sibling worker doesn't double-flip rows. Returns the number
    of rows touched so the caller can log it.
    """
    expiry_seconds = int(settings.wallet_deposit_expiry_seconds)
    if expiry_seconds <= 0:
        return 0

    cutoff = utcnow() - timedelta(seconds=expiry_seconds)

    rows = (
        (
            await session.execute(
                select(WalletDeposit)
                .where(
                    WalletDeposit.status == WalletDepositStatus.pending,
                    WalletDeposit.created_at <= cutoff,
                )
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )

    if not rows:
        return 0

    for row in rows:
        row.status = WalletDepositStatus.expired

    await session.commit()
    return len(rows)


async def poll_deposit_status(session: AsyncSession, deposit: WalletDeposit) -> WalletDeposit:
    """Refresh a pending deposit's status from CryptoBot. Idempotent."""
    if deposit.status != WalletDepositStatus.pending:
        return deposit
    if not settings.cryptobot_token:
        return deposit
    try:
        async with CryptoPay(
            settings.cryptobot_token, testnet=settings.cryptobot_testnet
        ) as crypto:
            rows = await crypto.get_invoices(invoice_ids=[int(deposit.provider_invoice_id)])
    except CryptoPayError as e:
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


async def _auto_withdraw_enabled(session: AsyncSession) -> bool:
    row = (
        await session.execute(select(AppSettings).order_by(AppSettings.id).limit(1))
    ).scalar_one_or_none()
    return bool(row and row.auto_withdraw_enabled)


def _cryptopay_configured() -> bool:
    token = settings.cryptobot_token or ""
    return bool(token) and not token.startswith("000")


async def create_withdrawal(
    session: AsyncSession, user: User, currency_code: str, amount: float, address: str
) -> WalletWithdrawal:
    currency = await get_currency_by_code(session, currency_code)
    if amount < float(currency.min_withdraw):
        raise HTTPException(
            400, f"Минимальная сумма вывода: {currency.min_withdraw} {currency.code}"
        )

    # Row-lock the balance: two concurrent withdrawals must not both
    # pass the ``amount >= price`` check on the same balance.
    bal = await lock_user_balance(session, user.id, currency.id)
    amount_d = Decimal(str(amount))
    current = Decimal(str(bal.amount))
    if current < amount_d:
        raise HTTPException(400, "Недостаточно средств")

    # Decimal end-to-end: ``Numeric(18,8)`` accepts Decimal natively;
    # round-tripping through ``float`` (the previous M5 buggy path)
    # drops the last 2-3 significant digits at the 10^10 scale that
    # USDT can hit.
    bal.amount = current - amount_d
    bal.locked = Decimal(str(bal.locked)) + amount_d

    withdrawal = WalletWithdrawal(
        user_id=user.id,
        currency_id=currency.id,
        amount=amount,
        address=address,
        status=WalletWithdrawStatus.pending,
        locked_until=utcnow() + timedelta(hours=WITHDRAW_LOCK_HOURS),
    )
    session.add(withdrawal)
    await session.commit()
    await session.refresh(withdrawal)

    # If auto-mode is on and CryptoBot is configured, fire the transfer
    # immediately so the user doesn't wait on an admin. Failures here
    # leave the withdrawal in ``pending`` so admins can still approve
    # manually.
    if await _auto_withdraw_enabled(session) and _cryptopay_configured():
        try:
            async with CryptoPay(
                settings.cryptobot_token, testnet=settings.cryptobot_testnet
            ) as cp:
                tr = await cp.transfer(
                    user_id=user.tg_user_id,
                    asset=currency.code,
                    amount=str(amount),
                    spend_id=f"wd:{withdrawal.id}",
                    comment=f"Garant withdrawal #{withdrawal.id}",
                )
        except CryptoPayError as e:
            logger.warning(
                "auto-withdraw #%s CryptoBot transfer failed: %s — leaving pending",
                withdrawal.id,
                e,
            )
        else:
            withdrawal.status = WalletWithdrawStatus.sent
            withdrawal.processed_at = utcnow()
            withdrawal.admin_note = f"cryptobot_transfer_id={tr.transfer_id}"
            bal.locked = max(Decimal(0), Decimal(str(bal.locked)) - amount_d)
            await notifier.push(
                session,
                user.id,
                NotificationType.deposits,
                "Вывод выполнен",
                f"-{amount} {currency.code} отправлены на {address}",
                {"withdrawal_id": withdrawal.id},
            )
            await session.commit()
            await session.refresh(withdrawal)
            return withdrawal

    # Manual mode (or auto failed): queue for admin review.
    admins = (await session.execute(select(User).where(User.is_admin.is_(True)))).scalars().all()
    for admin in admins:
        await notifier.push(
            session,
            admin.id,
            NotificationType.system,
            "Заявка на вывод",
            f"@{user.username or user.tg_user_id}: {amount} {currency.code} → {address[:12]}…",
            {"withdrawal_id": withdrawal.id},
        )
    if admins:
        await session.commit()

    return withdrawal


# NOTE: the legacy ``decide_withdrawal`` service was removed — the
# canonical admin decide flow now lives in
# ``backend.app.routers.admin.withdrawals.decide_withdrawal`` which
# writes audit rows, holds row locks, and handles auto-mode
# CryptoBot transfers.
