"""Legacy services kept after the PR-3 state-machine refactor.

Deal lifecycle moved to :mod:`backend.app.services_deals` (multi-currency,
10-status state-machine). This module now only carries:

* :func:`post_review` — review posting (unchanged).
* :func:`credit_invoice` — legacy USD invoice crediting via the old
  ``User.balance`` column. Used by the deprecated ``/api/payments/*``
  routes, kept for backward-compat until that surface is retired.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import notifier
from .models import (
    Deal,
    DealStatus,
    Invoice,
    InvoiceStatus,
    NotificationType,
    Review,
    User,
)
from .time_utils import utcnow

# Deal states in which a counter-party review is allowed.
REVIEWABLE_DEAL_STATUSES = frozenset(
    {
        DealStatus.completed,
        DealStatus.resolved_for_buyer,
        DealStatus.resolved_for_seller,
    }
)


async def _recompute_user_rating(session: AsyncSession, target: User) -> None:
    """Recompute ``good``/``bad`` counters from the live ``reviews`` table.

    Counts every received review for this user:
    * ``rating >= 4`` → good
    * ``rating <= 2`` → bad
    * ``rating == 3`` → neutral (excluded from both counters)
    """
    good = (
        await session.execute(
            select(func.count(Review.id)).where(Review.target_id == target.id, Review.rating >= 4)
        )
    ).scalar_one()
    bad = (
        await session.execute(
            select(func.count(Review.id)).where(Review.target_id == target.id, Review.rating <= 2)
        )
    ).scalar_one()
    target.good = int(good or 0)
    target.bad = int(bad or 0)


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
    if len(text) > 1024:
        raise ValueError("Текст отзыва слишком длинный (≤1024)")

    if deal_id is None:
        raise ValueError("Отзыв можно оставить только по конкретной сделке")

    deal = await session.get(Deal, deal_id)
    if deal is None:
        raise ValueError("Сделка не найдена")
    if author.id not in (deal.buyer_id, deal.seller_id):
        raise ValueError("Вы не участвуете в этой сделке")
    counterparty_id = deal.seller_id if author.id == deal.buyer_id else deal.buyer_id
    if counterparty_id != target.id:
        raise ValueError("Можно оставить отзыв только контрагенту по сделке")
    if deal.status not in REVIEWABLE_DEAL_STATUSES:
        raise ValueError("Отзыв доступен только после завершения сделки")

    existing = (
        await session.execute(
            select(Review).where(Review.author_id == author.id, Review.deal_id == deal_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError("Вы уже оставили отзыв по этой сделке")

    review = Review(
        author_id=author.id,
        target_id=target.id,
        deal_id=deal_id,
        rating=rating,
        text=text,
    )
    session.add(review)
    await session.flush()

    await _recompute_user_rating(session, target)

    await notifier.push(
        session,
        target.id,
        NotificationType.system,
        "Новый отзыв",
        f"@{author.username} оставил отзыв ({rating}/5)",
        {"review_id": review.id},
    )
    await session.commit()
    await session.refresh(review)

    return review


async def credit_invoice(
    session: AsyncSession,
    invoice: Invoice,
) -> Invoice:
    if invoice.status == InvoiceStatus.paid:
        return invoice

    # V5-B-2 — take a FOR UPDATE lock on the User row that holds the
    # legacy ``balance`` column BEFORE mutating it. ``credit_invoice``
    # is called from two callers:
    #
    # * :func:`services_payments.handle_invoice_paid`, which now also
    #   locks the Invoice row before getting here (the webhook path,
    #   V5-B-2 step 1), and
    # * :func:`backend.app.routers.payments.check_invoice`, the
    #   polling fallback, which does a plain ``session.get(Invoice,
    #   ...)`` without a lock.
    #
    # Locking the User row serialises the second caller against any
    # concurrent webhook delivery for the SAME owner: the webhook
    # holds the User lock while it RMW-s ``owner.balance``, and the
    # polling path blocks here until that commits. We then refresh
    # ``invoice`` from the DB and re-check ``invoice.status`` — the
    # loser of the race observes ``paid`` and returns idempotently
    # without double-crediting the user.
    owner = (
        await session.execute(
            select(User).where(User.id == invoice.owner_id).with_for_update()
        )
    ).scalar_one_or_none()

    await session.refresh(invoice, attribute_names=["status", "paid_at"])
    if invoice.status == InvoiceStatus.paid:
        return invoice

    invoice.status = InvoiceStatus.paid
    invoice.paid_at = utcnow()

    if owner:
        owner.balance = Decimal(str(owner.balance)) + Decimal(str(invoice.amount))

    if owner:
        await notifier.push(
            session,
            owner.id,
            NotificationType.deposits,
            "Депозит зачислен",
            f"${float(invoice.amount):.2f} зачислено на баланс",
        )

    await session.commit()
    await session.refresh(invoice)

    return invoice
