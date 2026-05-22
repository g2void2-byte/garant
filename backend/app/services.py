"""Legacy services kept after the PR-3 state-machine refactor.

Deal lifecycle moved to :mod:`backend.app.services_deals` (multi-currency,
10-status state-machine). This module now only carries:

* :func:`post_review` — review posting (unchanged).
* :func:`sweep_user_last_ip` — GDPR retention sweep for ``users.last_ip``.

H-1 retired ``credit_invoice`` and ``sweep_expired_invoices`` together
with the legacy USD ``Invoice`` ledger; the surviving wallet ledger
has its own ``credit_deposit`` / ``sweep_expired_deposits`` in
:mod:`backend.app.services_wallet`.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import notifier
from .config import settings
from .models import (
    Deal,
    DealStatus,
    NotificationType,
    Review,
    User,
)
from .time_utils import utcnow

logger = logging.getLogger(__name__)

# Deal states in which a counter-party review is allowed.
REVIEWABLE_DEAL_STATUSES = frozenset(
    {
        DealStatus.completed,
        DealStatus.resolved_for_buyer,
        DealStatus.resolved_for_seller,
    }
)


async def recompute_user_rating(session: AsyncSession, target: User) -> None:
    """Recompute ``good``/``bad`` counters from the live ``reviews`` table.

    Counts every received review for this user:
    * ``rating >= 4`` → good
    * ``rating <= 2`` → bad
    * ``rating == 3`` → neutral (excluded from both counters)

    single round-trip ``SUM(CASE ...)`` instead of two
    ``SELECT COUNT(...)``.  ``post_review`` is on the hot path for
    every newly-finished deal; cutting the recompute from two
    sequential queries to one halves the DB round-trips per review
    and lets Postgres scan the per-target index just once.
    """
    good_expr = func.coalesce(func.sum(case((Review.rating >= 4, 1), else_=0)), 0)
    bad_expr = func.coalesce(func.sum(case((Review.rating <= 2, 1), else_=0)), 0)
    good, bad = (
        await session.execute(select(good_expr, bad_expr).where(Review.target_id == target.id))
    ).one()
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

    await recompute_user_rating(session, target)

    # A9-M-2 — split-API: persist the notification row atomically with
    # the review insert + rating recompute, dispatch WS/DM after commit
    # so a rolled-back transaction never leaks a "new review" toast.
    notif, ws_payload = await notifier.insert(
        session,
        target.id,
        NotificationType.system,
        "Новый отзыв",
        f"@{author.username} оставил отзыв ({rating}/5)",
        {"review_id": review.id},
    )
    await session.commit()
    try:
        await notifier.dispatch_after_commit(session, notif, ws_payload)
    except Exception:
        logger.exception(
            "post_review: post-commit dispatch failed for notif id=%s",
            notif.id,
            extra={"event": "post_review.dispatch.failed", "notif_id": notif.id},
        )

    return review


async def sweep_user_last_ip(session: AsyncSession) -> int:
    """Null out ``users.last_ip`` older than the retention window.

    Comment 45 (audit v10, GDPR): IP addresses are PII. We keep them
    for the configured retention period (default 90 days) for abuse
    investigation, then scrub them so the platform doesn't accumulate
    PII indefinitely.
    """
    retention = int(settings.last_ip_retention_seconds)
    if retention <= 0:
        return 0
    cutoff = utcnow() - timedelta(seconds=retention)
    from sqlalchemy import update

    result = await session.execute(
        update(User)
        .where(
            User.last_ip.is_not(None),
            User.last_login_at.is_not(None),
            User.last_login_at <= cutoff,
        )
        .values(last_ip=None)
    )
    await session.commit()
    return result.rowcount  # type: ignore[return-value]
