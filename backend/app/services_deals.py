"""Deal escrow on top of the multi-currency wallet (PR-3).

The state machine has 10 statuses (see ``DealStatus`` in ``models.py``).
Money flow uses the per-currency ``UserBalance`` rows introduced in
PR-2 — the legacy ``User.balance`` USD column is no longer touched
when a deal is created via this module.

High-level transitions:

    create()                 →  PENDING_CONFIRMATION
    accept   (seller)        →  IN_PROGRESS
    decline  (seller)        →  CANCELLED         (refund buyer)
    finish   (buyer)         →  COMPLETED         (pay seller)
    cancel_request   (any)   →  PENDING_CANCELLATION
    revoke_cancel    (init.) →  IN_PROGRESS
    accept_cancel    (other) →  CANCELLED         (refund buyer)
    debate           (any)   →  ARBITRATION
    resolve          (admin) →  RESOLVED_FOR_{BUYER|SELLER}
    sweep_inactivity (cron)  →  CANCELLED_FOR_INACTIVITY (PC stale)
                                CANCELLED                (PCANC stale)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import notifier
from .models import (
    AppSettings,
    Currency,
    Deal,
    DealStatus,
    NotificationType,
    PayCommission,
    User,
    UserBalance,
)
from .services_wallet import get_currency_by_code, get_or_create_balance

logger = logging.getLogger(__name__)


# ── Settings helper ────────────────────────────────────


async def _settings(session: AsyncSession) -> AppSettings:
    result = await session.execute(select(AppSettings).limit(1))
    s = result.scalar_one_or_none()
    if s is None:
        s = AppSettings()
        session.add(s)
        await session.commit()
        await session.refresh(s)
    return s


def _q(value: Decimal | float | int, decimals: int) -> Decimal:
    """Quantise to the currency's precision."""
    quant = Decimal(10) ** -decimals
    return Decimal(str(value)).quantize(quant)


def _commission(amount: Decimal, percent: Decimal | float, decimals: int) -> Decimal:
    return _q(amount * Decimal(str(percent)) / Decimal(100), decimals)


# ── Balance helpers ────────────────────────────────────


async def _debit(
    session: AsyncSession, user_id: int, currency_id: int, amount: Decimal
) -> UserBalance:
    bal = await get_or_create_balance(session, user_id, currency_id)
    if Decimal(str(bal.amount)) < amount:
        raise ValueError("Недостаточно средств")
    bal.amount = float(Decimal(str(bal.amount)) - amount)
    bal.locked = float(Decimal(str(bal.locked)) + amount)
    return bal


async def _refund(
    session: AsyncSession, user_id: int, currency_id: int, amount: Decimal
) -> UserBalance:
    bal = await get_or_create_balance(session, user_id, currency_id)
    bal.locked = float(max(Decimal(0), Decimal(str(bal.locked)) - amount))
    bal.amount = float(Decimal(str(bal.amount)) + amount)
    return bal


async def _release_to(
    session: AsyncSession,
    payer_id: int,
    payee_id: int,
    currency_id: int,
    locked_amount: Decimal,
    payout_amount: Decimal,
) -> None:
    """Unlock ``locked_amount`` from payer and credit ``payout_amount`` to payee.

    The diff (``locked_amount - payout_amount``) is the platform commission;
    it stays in payer's locked → effectively "burns" it into the platform
    pool. The platform's own ledger isn't modeled in PR-3.
    """
    payer = await get_or_create_balance(session, payer_id, currency_id)
    payer.locked = float(max(Decimal(0), Decimal(str(payer.locked)) - locked_amount))
    payee = await get_or_create_balance(session, payee_id, currency_id)
    payee.amount = float(Decimal(str(payee.amount)) + payout_amount)


# ── Lifecycle ──────────────────────────────────────────


async def create_deal(
    session: AsyncSession,
    buyer: User,
    seller: User,
    currency_code: str,
    amount: float | Decimal,
    description: str,
    pay_commission: PayCommission,
) -> Deal:
    """Create a deal and lock buyer funds.

    ``amount`` is the headline price. If the buyer pays commission, the
    locked sum is ``amount + commission``; if the seller pays commission,
    the locked sum is ``amount`` and commission is taken from the
    seller's payout at finish time.
    """
    if buyer.id == seller.id:
        raise ValueError("Нельзя создать сделку с самим собой")

    currency = await get_currency_by_code(session, currency_code)
    settings = await _settings(session)
    amt = _q(Decimal(str(amount)), currency.decimals)
    if amt <= 0:
        raise ValueError("Сумма должна быть больше нуля")

    commission = _commission(amt, settings.deal_commission_percent, currency.decimals)
    locked = amt + commission if pay_commission == PayCommission.buyer else amt
    await _debit(session, buyer.id, currency.id, locked)

    deal = Deal(
        buyer_id=buyer.id,
        seller_id=seller.id,
        sum=float(amt),  # legacy column for backward-compat
        amount=float(amt),
        commission_amount=float(commission),
        currency_id=currency.id,
        description=description,
        pay_commission=pay_commission,
        status=DealStatus.pending_confirmation,
    )
    session.add(deal)
    buyer.deals_total += 1
    seller.deals_total += 1
    await session.commit()
    await session.refresh(deal)

    await notifier.push(
        session,
        seller.id,
        NotificationType.deals,
        "Новая сделка",
        f"@{buyer.username or buyer.tg_user_id} создал сделку #{deal.id} на {amt} {currency.code}",
        {"deal_id": deal.id},
    )
    return deal


async def accept_deal(session: AsyncSession, deal: Deal, user: User) -> Deal:
    if user.id != deal.seller_id:
        raise ValueError("Принять сделку может только продавец")
    if deal.status != DealStatus.pending_confirmation:
        raise ValueError("Сделку нельзя принять в текущем статусе")

    deal.status = DealStatus.in_progress
    deal.in_progress_at = datetime.utcnow()
    deal.confirm_buyer = True
    deal.confirm_seller = True
    await session.commit()
    await session.refresh(deal)

    await notifier.push(
        session,
        deal.buyer_id,
        NotificationType.deals,
        "Сделка принята",
        f"Продавец принял сделку #{deal.id}",
        {"deal_id": deal.id},
    )
    return deal


async def decline_deal(session: AsyncSession, deal: Deal, user: User) -> Deal:
    if user.id != deal.seller_id:
        raise ValueError("Отклонить сделку может только продавец")
    if deal.status != DealStatus.pending_confirmation:
        raise ValueError("Сделку нельзя отклонить в текущем статусе")
    if deal.currency_id is None or deal.amount is None:
        raise ValueError("У сделки не задана валюта")

    settings = await _settings(session)
    currency = await session.get(Currency, deal.currency_id)
    assert currency is not None
    amt = _q(Decimal(str(deal.amount)), currency.decimals)
    commission = _q(Decimal(str(deal.commission_amount or 0)), currency.decimals) or _commission(
        amt, settings.deal_commission_percent, currency.decimals
    )
    locked = amt + commission if deal.pay_commission == PayCommission.buyer else amt
    await _refund(session, deal.buyer_id, currency.id, locked)

    deal.status = DealStatus.cancelled
    deal.completed_at = datetime.utcnow()
    await session.commit()
    await session.refresh(deal)

    await notifier.push(
        session,
        deal.buyer_id,
        NotificationType.deals,
        "Сделка отклонена",
        f"Продавец отклонил сделку #{deal.id}. Средства возвращены.",
        {"deal_id": deal.id},
    )
    return deal


async def finish_deal(session: AsyncSession, deal: Deal, user: User) -> Deal:
    if user.id != deal.buyer_id:
        raise ValueError("Завершить сделку может только покупатель")
    if deal.status != DealStatus.in_progress:
        raise ValueError("Сделку нельзя завершить в текущем статусе")
    if deal.currency_id is None or deal.amount is None:
        raise ValueError("У сделки не задана валюта")

    currency = await session.get(Currency, deal.currency_id)
    assert currency is not None
    amt = _q(Decimal(str(deal.amount)), currency.decimals)
    commission = _q(Decimal(str(deal.commission_amount or 0)), currency.decimals)

    if deal.pay_commission == PayCommission.buyer:
        locked = amt + commission
        payout = amt
    else:
        locked = amt
        payout = amt - commission

    await _release_to(session, deal.buyer_id, deal.seller_id, currency.id, locked, payout)

    deal.status = DealStatus.completed
    deal.completed_at = datetime.utcnow()
    buyer = await session.get(User, deal.buyer_id)
    seller = await session.get(User, deal.seller_id)
    if buyer:
        buyer.deals_success += 1
    if seller:
        seller.deals_success += 1
    await session.commit()
    await session.refresh(deal)

    await notifier.push(
        session,
        deal.seller_id,
        NotificationType.deals,
        "Сделка завершена",
        f"Вы получили {payout} {currency.code} по сделке #{deal.id}",
        {"deal_id": deal.id},
    )
    return deal


# ── Cancel-debate (soft cancel) ────────────────────────


async def request_cancel(session: AsyncSession, deal: Deal, user: User, reason: str) -> Deal:
    if user.id not in (deal.buyer_id, deal.seller_id):
        raise ValueError("Вы не участник сделки")
    if deal.status != DealStatus.in_progress:
        raise ValueError("Отмену можно запросить только во время работы по сделке")

    deal.status = DealStatus.pending_cancellation
    deal.cancellation_initiator_id = user.id
    deal.cancellation_reason = reason
    deal.cancellation_requested_at = datetime.utcnow()
    await session.commit()
    await session.refresh(deal)

    other_id = deal.seller_id if user.id == deal.buyer_id else deal.buyer_id
    await notifier.push(
        session,
        other_id,
        NotificationType.deals,
        "Запрос отмены",
        f"По сделке #{deal.id} запрошена отмена: {reason or '—'}",
        {"deal_id": deal.id},
    )
    return deal


async def revoke_cancel(session: AsyncSession, deal: Deal, user: User) -> Deal:
    if deal.status != DealStatus.pending_cancellation:
        raise ValueError("Запроса на отмену нет")
    if user.id != deal.cancellation_initiator_id:
        raise ValueError("Отозвать запрос может только инициатор")

    deal.status = DealStatus.in_progress
    deal.cancellation_initiator_id = None
    deal.cancellation_reason = None
    deal.cancellation_requested_at = None
    await session.commit()
    await session.refresh(deal)

    other_id = deal.seller_id if user.id == deal.buyer_id else deal.buyer_id
    await notifier.push(
        session,
        other_id,
        NotificationType.deals,
        "Запрос отмены отозван",
        f"По сделке #{deal.id} запрос отмены отозван",
        {"deal_id": deal.id},
    )
    return deal


async def accept_cancel(session: AsyncSession, deal: Deal, user: User) -> Deal:
    if deal.status != DealStatus.pending_cancellation:
        raise ValueError("Запроса на отмену нет")
    if user.id not in (deal.buyer_id, deal.seller_id):
        raise ValueError("Вы не участник сделки")
    if user.id == deal.cancellation_initiator_id:
        raise ValueError("Инициатор не может согласиться с собственным запросом отмены")
    if deal.currency_id is None or deal.amount is None:
        raise ValueError("У сделки не задана валюта")

    settings = await _settings(session)
    currency = await session.get(Currency, deal.currency_id)
    assert currency is not None
    amt = _q(Decimal(str(deal.amount)), currency.decimals)
    commission = _q(Decimal(str(deal.commission_amount or 0)), currency.decimals) or _commission(
        amt, settings.deal_commission_percent, currency.decimals
    )
    locked = amt + commission if deal.pay_commission == PayCommission.buyer else amt
    await _refund(session, deal.buyer_id, currency.id, locked)

    deal.status = DealStatus.cancelled
    deal.completed_at = datetime.utcnow()
    await session.commit()
    await session.refresh(deal)

    await notifier.push(
        session,
        deal.cancellation_initiator_id or deal.buyer_id,
        NotificationType.deals,
        "Сделка отменена",
        f"По сделке #{deal.id} отмена согласована. Средства возвращены.",
        {"deal_id": deal.id},
    )
    return deal


# ── Arbitration ────────────────────────────────────────


_ARBITRATION_ELIGIBLE = (
    DealStatus.in_progress,
    DealStatus.pending_cancellation,
)


async def start_arbitration(session: AsyncSession, deal: Deal, user: User, reason: str) -> Deal:
    if user.id not in (deal.buyer_id, deal.seller_id):
        raise ValueError("Вы не участник сделки")
    if deal.status not in _ARBITRATION_ELIGIBLE:
        raise ValueError("Сделку нельзя передать в арбитраж в текущем статусе")
    if not reason or not reason.strip():
        raise ValueError("Опишите причину арбитража")

    deal.status = DealStatus.arbitration
    deal.arbitration_initiator_id = user.id
    deal.arbitration_reason = reason
    # Legacy mirror for any old readers.
    deal.arbitrage_reason = reason

    buyer = await session.get(User, deal.buyer_id)
    seller = await session.get(User, deal.seller_id)
    if buyer:
        buyer.deals_arbitrage += 1
    if seller:
        seller.deals_arbitrage += 1
    await session.commit()
    await session.refresh(deal)

    arbiters = (
        (await session.execute(select(User).where(User.is_arbiter.is_(True)))).scalars().all()
    )
    admins = (await session.execute(select(User).where(User.is_admin.is_(True)))).scalars().all()
    seen: set[int] = set()
    for recipient in [*arbiters, *admins]:
        if recipient.id in seen:
            continue
        seen.add(recipient.id)
        await notifier.push(
            session,
            recipient.id,
            NotificationType.deals,
            "Арбитраж",
            f"Сделка #{deal.id} передана в арбитраж: {reason}",
            {"deal_id": deal.id},
        )
    return deal


async def resolve_arbitration(
    session: AsyncSession,
    deal: Deal,
    admin: User,
    winner: str,
    note: str = "",
) -> Deal:
    if not (admin.is_admin or admin.is_arbiter):
        raise ValueError("Только администратор или арбитр может разрешать спор")
    if deal.status != DealStatus.arbitration:
        raise ValueError("Сделка не в статусе арбитража")
    if winner not in ("buyer", "seller"):
        raise ValueError("winner должен быть 'buyer' или 'seller'")
    if deal.currency_id is None or deal.amount is None:
        raise ValueError("У сделки не задана валюта")

    currency = await session.get(Currency, deal.currency_id)
    assert currency is not None
    amt = _q(Decimal(str(deal.amount)), currency.decimals)
    commission = _q(Decimal(str(deal.commission_amount or 0)), currency.decimals)

    if winner == "buyer":
        # Refund the buyer in full (incl. their commission contribution).
        locked = amt + commission if deal.pay_commission == PayCommission.buyer else amt
        await _refund(session, deal.buyer_id, currency.id, locked)
        deal.status = DealStatus.resolved_for_buyer
    else:
        if deal.pay_commission == PayCommission.buyer:
            locked = amt + commission
            payout = amt
        else:
            locked = amt
            payout = amt - commission
        await _release_to(session, deal.buyer_id, deal.seller_id, currency.id, locked, payout)
        deal.status = DealStatus.resolved_for_seller

    deal.arbitration_resolved_by = admin.id
    deal.arbitration_resolution = winner
    deal.arbitration_resolved_at = datetime.utcnow()
    deal.completed_at = datetime.utcnow()
    if note:
        deal.arbitration_reason = (
            f"{deal.arbitration_reason or ''}\n— Решение арбитра: {note}".strip()
        )

    await session.commit()
    await session.refresh(deal)

    winner_id = deal.buyer_id if winner == "buyer" else deal.seller_id
    loser_id = deal.seller_id if winner == "buyer" else deal.buyer_id
    await notifier.push(
        session,
        winner_id,
        NotificationType.deals,
        "Спор решён в вашу пользу",
        f"Арбитр вынес решение по сделке #{deal.id}",
        {"deal_id": deal.id},
    )
    await notifier.push(
        session,
        loser_id,
        NotificationType.deals,
        "Спор решён не в вашу пользу",
        f"Арбитр вынес решение по сделке #{deal.id}",
        {"deal_id": deal.id},
    )
    return deal


# ── Inactivity sweep ───────────────────────────────────


async def sweep_inactivity(session: AsyncSession) -> int:
    """Auto-cancel stale deals.

    * ``PENDING_CONFIRMATION`` older than ``inactivity_pending_confirmation_days``
      → ``CANCELLED_FOR_INACTIVITY`` and refund buyer.
    * ``PENDING_CANCELLATION`` older than ``inactivity_pending_cancellation_days``
      → ``CANCELLED`` and refund buyer.

    Returns the number of deals affected.
    """
    settings = await _settings(session)
    now = datetime.utcnow()
    pc_cutoff = now - timedelta(days=int(settings.inactivity_pending_confirmation_days))
    pcanc_cutoff = now - timedelta(days=int(settings.inactivity_pending_cancellation_days))

    affected = 0
    rows = (
        (
            await session.execute(
                select(Deal).where(
                    or_(
                        (Deal.status == DealStatus.pending_confirmation)
                        & (Deal.created_at <= pc_cutoff),
                        (Deal.status == DealStatus.pending_cancellation)
                        & (Deal.cancellation_requested_at.is_not(None))
                        & (Deal.cancellation_requested_at <= pcanc_cutoff),
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    for deal in rows:
        if deal.currency_id is None or deal.amount is None:
            continue
        currency = await session.get(Currency, deal.currency_id)
        if currency is None:
            continue
        amt = _q(Decimal(str(deal.amount)), currency.decimals)
        commission = _q(Decimal(str(deal.commission_amount or 0)), currency.decimals)
        locked = amt + commission if deal.pay_commission == PayCommission.buyer else amt
        await _refund(session, deal.buyer_id, currency.id, locked)
        target_status = (
            DealStatus.cancelled_for_inactivity
            if deal.status == DealStatus.pending_confirmation
            else DealStatus.cancelled
        )
        deal.status = target_status
        deal.completed_at = now
        await session.commit()

        for recipient_id in (deal.buyer_id, deal.seller_id):
            await notifier.push(
                session,
                recipient_id,
                NotificationType.deals,
                "Сделка отменена за неактивность",
                f"Сделка #{deal.id} автоматически закрыта.",
                {"deal_id": deal.id},
            )
        affected += 1
    return affected
