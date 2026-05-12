"""Domain logic for escrow deals + balance bookkeeping."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Deal, DealStatus, Setting, Transaction, TxType, User


async def get_setting(session: AsyncSession, key: str, default: str) -> str:
    res = await session.execute(select(Setting).where(Setting.key == key))
    row = res.scalar_one_or_none()
    return row.value if row else default


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    res = await session.execute(select(Setting).where(Setting.key == key))
    row = res.scalar_one_or_none()
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value


async def commission_percent(session: AsyncSession) -> float:
    return float(await get_setting(session, "commission_percent", str(settings.commission_percent)))


async def insurance_deposit(session: AsyncSession) -> float:
    return float(await get_setting(session, "insurance_deposit", str(settings.insurance_deposit)))


async def welcome_message(session: AsyncSession) -> str:
    return await get_setting(session, "welcome_message", settings.welcome_message)


def _add_tx(
    session: AsyncSession,
    user: User,
    tx_type: TxType,
    amount: float,
    *,
    deal_id: int | None = None,
    note: str | None = None,
) -> None:
    session.add(
        Transaction(
            user_id=user.id,
            type=tx_type,
            amount=amount,
            deal_id=deal_id,
            note=note,
        )
    )


async def deposit(session: AsyncSession, user: User, amount: float, note: str | None = None) -> None:
    if amount <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Amount must be positive")
    user.balance += amount
    _add_tx(session, user, TxType.DEPOSIT, amount, note=note)


async def withdraw(session: AsyncSession, user: User, amount: float, note: str | None = None) -> None:
    if amount <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Amount must be positive")
    if user.balance < amount:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Insufficient balance")
    user.balance -= amount
    _add_tx(session, user, TxType.WITHDRAW, amount, note=note)


async def lock_insurance(session: AsyncSession, user: User) -> None:
    """Move money from balance to insurance pool (one-time per user)."""
    required = await insurance_deposit(session)
    if user.insurance >= required:
        return
    needed = required - user.insurance
    if user.balance < needed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Недостаточно средств для страхового депозита (нужно ${needed:.2f})",
        )
    user.balance -= needed
    user.insurance += needed
    _add_tx(session, user, TxType.INSURANCE_LOCK, needed, note="Insurance deposit")


async def unlock_insurance(session: AsyncSession, user: User) -> None:
    if user.insurance <= 0:
        return
    amount = user.insurance
    user.balance += amount
    user.insurance = 0.0
    _add_tx(session, user, TxType.INSURANCE_UNLOCK, amount, note="Insurance refunded")


async def resolve_counterparty(
    session: AsyncSession,
    *,
    tg_id: int | None,
    username: str | None,
) -> User:
    if tg_id is None and not username:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Counterparty required")
    stmt = select(User)
    if tg_id is not None:
        stmt = stmt.where(User.tg_id == tg_id)
    else:
        stmt = stmt.where(func.lower(User.username) == (username or "").lstrip("@").lower())
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Контрагент не найден. Он должен сначала зайти в бота.",
        )
    return user


async def create_deal(
    session: AsyncSession,
    *,
    creator: User,
    counterparty: User,
    role: str,
    title: str,
    description: str,
    amount: float,
) -> Deal:
    if creator.id == counterparty.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя создать сделку с самим собой")
    if amount <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Сумма должна быть положительной")

    buyer, seller = (creator, counterparty) if role == "buyer" else (counterparty, creator)
    percent = await commission_percent(session)
    commission = round(amount * percent / 100.0, 2)

    # Seller must have the insurance deposit locked
    await lock_insurance(session, seller)

    deal = Deal(
        title=title,
        description=description,
        amount=amount,
        commission=commission,
        status=DealStatus.AWAITING_PAYMENT,
        buyer_id=buyer.id,
        seller_id=seller.id,
        creator_id=creator.id,
    )
    session.add(deal)
    await session.flush()
    return deal


async def fund_deal(session: AsyncSession, deal: Deal, actor: User) -> None:
    if actor.id != deal.buyer_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только покупатель может оплатить сделку")
    if deal.status != DealStatus.AWAITING_PAYMENT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Сделка не ожидает оплаты")

    total = deal.amount + deal.commission
    if actor.balance < total:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недостаточно средств на балансе")

    actor.balance -= total
    actor.frozen += deal.amount
    _add_tx(session, actor, TxType.HOLD, deal.amount, deal_id=deal.id, note="Escrow hold")
    _add_tx(
        session, actor, TxType.COMMISSION, deal.commission, deal_id=deal.id, note="Service fee"
    )

    deal.status = DealStatus.FUNDED
    deal.funded_at = datetime.now(UTC)


async def confirm_deal(session: AsyncSession, deal: Deal, actor: User) -> None:
    if actor.id != deal.buyer_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только покупатель подтверждает сделку")
    if deal.status != DealStatus.FUNDED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Сделка не оплачена")

    # Release funds to seller
    seller = deal.seller
    buyer = deal.buyer
    buyer.frozen -= deal.amount
    seller.balance += deal.amount
    _add_tx(session, seller, TxType.RELEASE, deal.amount, deal_id=deal.id, note="Escrow release")

    deal.status = DealStatus.COMPLETED
    deal.completed_at = datetime.now(UTC)

    # Update ratings + deal counters
    for u in (buyer, seller):
        u.deals_total += 1
        u.deals_success += 1
        # gentle nudge toward 5.0
        u.rating = round(min(5.0, u.rating + 0.05), 2)


async def cancel_deal(session: AsyncSession, deal: Deal, actor: User) -> None:
    if deal.status not in (DealStatus.AWAITING_PAYMENT,):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Сделку можно отменить только до оплаты"
        )
    if actor.id not in (deal.buyer_id, deal.seller_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только участник сделки")
    deal.status = DealStatus.CANCELLED


async def open_dispute(session: AsyncSession, deal: Deal, actor: User, reason: str | None) -> None:
    if deal.status != DealStatus.FUNDED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Спор открывается только по оплаченной сделке")
    if actor.id not in (deal.buyer_id, deal.seller_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только участник сделки")
    deal.status = DealStatus.DISPUTED
    deal.dispute_reason = reason or "Без указания причины"


async def admin_release(session: AsyncSession, deal: Deal) -> None:
    """Force-release escrowed funds to the seller."""
    if deal.status not in (DealStatus.FUNDED, DealStatus.DISPUTED):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Сделку нельзя завершить из текущего статуса")
    buyer = deal.buyer
    seller = deal.seller
    buyer.frozen -= deal.amount
    seller.balance += deal.amount
    _add_tx(session, seller, TxType.RELEASE, deal.amount, deal_id=deal.id, note="Admin release")
    deal.status = DealStatus.COMPLETED
    deal.completed_at = datetime.now(UTC)
    buyer.deals_total += 1
    seller.deals_total += 1
    seller.deals_success += 1


async def admin_refund(session: AsyncSession, deal: Deal) -> None:
    """Force-refund escrowed funds back to the buyer."""
    if deal.status not in (DealStatus.FUNDED, DealStatus.DISPUTED):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Сделку нельзя вернуть из текущего статуса")
    buyer = deal.buyer
    seller = deal.seller
    buyer.frozen -= deal.amount
    buyer.balance += deal.amount
    _add_tx(session, buyer, TxType.REFUND, deal.amount, deal_id=deal.id, note="Admin refund")
    deal.status = DealStatus.REFUNDED
    deal.completed_at = datetime.now(UTC)
    buyer.deals_total += 1
    seller.deals_total += 1
    # Seller gets a rating penalty
    seller.rating = round(max(0.0, seller.rating - 0.3), 2)


async def aggregate_stats(session: AsyncSession) -> dict[str, float | int]:
    users_total = (await session.execute(select(func.count(User.id)))).scalar_one()
    cutoff = datetime.now(UTC) - timedelta(days=7)
    users_active = (
        await session.execute(select(func.count(User.id)).where(User.last_seen_at >= cutoff))
    ).scalar_one()
    deals_total = (await session.execute(select(func.count(Deal.id)))).scalar_one()
    deals_in_escrow = (
        await session.execute(
            select(func.count(Deal.id)).where(Deal.status == DealStatus.FUNDED)
        )
    ).scalar_one()
    volume = (
        await session.execute(
            select(func.coalesce(func.sum(Deal.amount), 0.0)).where(
                Deal.status == DealStatus.COMPLETED
            )
        )
    ).scalar_one()
    commission_sum = (
        await session.execute(
            select(func.coalesce(func.sum(Deal.commission), 0.0)).where(
                Deal.status == DealStatus.COMPLETED
            )
        )
    ).scalar_one()
    return {
        "users_total": int(users_total),
        "users_active_7d": int(users_active),
        "deals_total": int(deals_total),
        "deals_in_escrow": int(deals_in_escrow),
        "volume_total": float(volume),
        "commission_total": float(commission_sum),
    }
