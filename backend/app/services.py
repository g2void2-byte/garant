from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import notifier
from .models import (
    AppSettings,
    Deal,
    DealStatus,
    Invoice,
    InvoiceStatus,
    NotificationType,
    PayCommission,
    Review,
    User,
)


async def _get_settings(session: AsyncSession) -> AppSettings:
    result = await session.execute(select(AppSettings).limit(1))
    s = result.scalar_one_or_none()
    if s is None:
        s = AppSettings()
        session.add(s)
        await session.commit()
        await session.refresh(s)
    return s


async def create_deal(
    session: AsyncSession,
    buyer: User,
    seller: User,
    amount: float,
    description: str,
    pay_commission: PayCommission,
) -> Deal:
    settings = await _get_settings(session)
    commission = amount * float(settings.deal_commission_percent) / 100

    required = amount + commission if pay_commission == PayCommission.buyer else amount
    if float(buyer.balance) < required:
        raise ValueError("Недостаточно средств")

    buyer.balance = float(buyer.balance) - required
    buyer.frozen_balance = float(buyer.frozen_balance) + required

    deal = Deal(
        buyer_id=buyer.id,
        seller_id=seller.id,
        sum=amount,
        description=description,
        pay_commission=pay_commission,
        status=DealStatus.wait_confirm,
    )
    session.add(deal)
    buyer.deals_total += 1
    seller.deals_total += 1
    await session.commit()
    await session.refresh(deal)

    await notifier.push(
        session, seller.id, NotificationType.deals,
        "Новая сделка",
        f"Покупатель @{buyer.username} создал сделку на ${amount}",
        {"deal_id": deal.id},
    )

    return deal


async def confirm_deal(session: AsyncSession, deal: Deal, user: User) -> Deal:
    if deal.status != DealStatus.wait_confirm:
        raise ValueError("Сделка не в статусе ожидания подтверждения")

    if user.id == deal.buyer_id:
        if deal.confirm_buyer:
            raise ValueError("Вы уже подтвердили")
        deal.confirm_buyer = True
    elif user.id == deal.seller_id:
        if deal.confirm_seller:
            raise ValueError("Вы уже подтвердили")
        deal.confirm_seller = True
    else:
        raise ValueError("Вы не участник сделки")

    if deal.confirm_buyer and deal.confirm_seller:
        deal.status = DealStatus.confirmed

    await session.commit()
    await session.refresh(deal)

    counterparty_id = deal.seller_id if user.id == deal.buyer_id else deal.buyer_id
    await notifier.push(
        session, counterparty_id, NotificationType.deals,
        "Подтверждение сделки",
        f"@{user.username} подтвердил сделку #{deal.id}",
        {"deal_id": deal.id},
    )

    return deal


async def complete_deal(session: AsyncSession, deal: Deal, user: User) -> Deal:
    if deal.status not in (DealStatus.confirmed, DealStatus.wait_confirm):
        raise ValueError("Сделка не может быть завершена в текущем статусе")

    if user.id != deal.buyer_id:
        raise ValueError("Только покупатель может завершить сделку")

    settings = await _get_settings(session)
    commission = float(deal.sum) * float(settings.deal_commission_percent) / 100

    if deal.pay_commission == PayCommission.buyer:
        seller_amount = float(deal.sum)
        frozen_deduct = float(deal.sum) + commission
    else:
        seller_amount = float(deal.sum) - commission
        frozen_deduct = float(deal.sum)

    buyer = await session.get(User, deal.buyer_id)
    seller = await session.get(User, deal.seller_id)
    if buyer is None or seller is None:
        raise ValueError("Участник не найден")

    buyer.frozen_balance = float(buyer.frozen_balance) - frozen_deduct
    seller.balance = float(seller.balance) + seller_amount

    deal.status = DealStatus.success
    deal.completed_at = datetime.utcnow()

    buyer.deals_success += 1
    seller.deals_success += 1

    await session.commit()
    await session.refresh(deal)

    await notifier.push(
        session, seller.id, NotificationType.deals,
        "Сделка завершена",
        f"Вы получили ${seller_amount:.2f} по сделке #{deal.id}",
        {"deal_id": deal.id},
    )

    return deal


async def cancel_deal(session: AsyncSession, deal: Deal, user: User) -> Deal:
    if deal.status != DealStatus.wait_confirm:
        raise ValueError("Отмена возможна только до подтверждения обеими сторонами")

    settings = await _get_settings(session)
    commission = float(deal.sum) * float(settings.deal_commission_percent) / 100

    buyer = await session.get(User, deal.buyer_id)
    if buyer is None:
        raise ValueError("Покупатель не найден")

    if deal.pay_commission == PayCommission.buyer:
        refund = float(deal.sum) + commission
    else:
        refund = float(deal.sum)

    buyer.balance = float(buyer.balance) + refund
    buyer.frozen_balance = float(buyer.frozen_balance) - refund

    deal.status = DealStatus.failed
    deal.completed_at = datetime.utcnow()

    buyer.deals_failed += 1
    seller = await session.get(User, deal.seller_id)
    if seller:
        seller.deals_failed += 1

    await session.commit()
    await session.refresh(deal)

    counterparty_id = deal.seller_id if user.id == deal.buyer_id else deal.buyer_id
    await notifier.push(
        session, counterparty_id, NotificationType.deals,
        "Сделка отменена",
        f"@{user.username} отменил сделку #{deal.id}",
        {"deal_id": deal.id},
    )

    return deal


async def arbitrate_deal(
    session: AsyncSession, deal: Deal, user: User, reason: str = ""
) -> Deal:
    if deal.status in (DealStatus.success, DealStatus.failed):
        raise ValueError("Сделка уже завершена")

    if user.id not in (deal.buyer_id, deal.seller_id):
        raise ValueError("Вы не участник сделки")

    deal.status = DealStatus.arbitrage
    deal.arbitrage_reason = reason

    buyer = await session.get(User, deal.buyer_id)
    seller = await session.get(User, deal.seller_id)
    if buyer:
        buyer.deals_arbitrage += 1
    if seller:
        seller.deals_arbitrage += 1

    await session.commit()
    await session.refresh(deal)

    arbiter_stmt = select(User).where(User.is_arbiter.is_(True))
    result = await session.execute(arbiter_stmt)
    arbiters = result.scalars().all()
    for arb in arbiters:
        await notifier.push(
            session, arb.id, NotificationType.deals,
            "Арбитраж",
            f"Сделка #{deal.id} передана в арбитраж: {reason}",
            {"deal_id": deal.id},
        )

    return deal


async def post_review(
    session: AsyncSession,
    author: User,
    target: User,
    rating: int,
    text: str = "",
    deal_id: int | None = None,
) -> Review:
    if rating < 1 or rating > 5:
        raise ValueError("Рейтинг должен быть от 1 до 5")

    review = Review(
        author_id=author.id,
        target_id=target.id,
        deal_id=deal_id,
        rating=rating,
        text=text,
    )
    session.add(review)

    if rating >= 4:
        target.good += 1
    elif rating <= 2:
        target.bad += 1

    await session.commit()
    await session.refresh(review)

    await notifier.push(
        session, target.id, NotificationType.system,
        "Новый отзыв",
        f"@{author.username} оставил отзыв ({rating}/5)",
        {"review_id": review.id},
    )

    return review


async def credit_invoice(
    session: AsyncSession,
    invoice: Invoice,
) -> Invoice:
    if invoice.status == InvoiceStatus.paid:
        return invoice

    invoice.status = InvoiceStatus.paid
    invoice.paid_at = datetime.utcnow()

    owner = await session.get(User, invoice.owner_id)
    if owner:
        owner.balance = float(owner.balance) + float(invoice.amount)

    await session.commit()
    await session.refresh(invoice)

    if owner:
        await notifier.push(
            session, owner.id, NotificationType.deposits,
            "Депозит зачислен",
            f"${float(invoice.amount):.2f} зачислено на баланс",
        )

    return invoice
