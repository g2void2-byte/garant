"""Legacy services kept after the PR-3 state-machine refactor.

Deal lifecycle moved to :mod:`backend.app.services_deals` (multi-currency,
10-status state-machine). This module now only carries:

* :func:`post_review` — review posting (unchanged).
* :func:`credit_invoice` — legacy USD invoice crediting via the old
  ``User.balance`` column. Used by the deprecated ``/api/payments/*``
  routes, kept for backward-compat until that surface is retired.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from . import notifier
from .models import (
    Invoice,
    InvoiceStatus,
    NotificationType,
    Review,
    User,
)


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
