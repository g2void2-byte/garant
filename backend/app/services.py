"""Legacy services kept after the PR-3 state-machine refactor.

Deal lifecycle moved to :mod:`backend.app.services_deals` (multi-currency,
10-status state-machine). This module now only carries:

* :func:`post_review` — review posting (unchanged).
* :func:`credit_invoice` — legacy USD invoice crediting via the old
  ``User.balance`` column. Used by the deprecated ``/api/payments/*``
  routes, kept for backward-compat until that surface is retired.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import notifier
from .config import settings
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

    V5-D-10 — single round-trip ``SUM(CASE ...)`` instead of two
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
    # * :func:`services_payments.handle_invoice_paid` — locks the
    #   Invoice row via ``_find_legacy_invoice(lock=True)`` before
    #   getting here.
    # * :func:`backend.app.routers.payments.check_invoice` — the
    #   polling fallback, which now also locks the Invoice row via
    #   ``select(Invoice).with_for_update()
    #   .execution_options(populate_existing=True)`` (V5-B-2 follow-up).
    #
    # Both callers therefore acquire the same lock order
    # ``Invoice -> User``. The User-row lock here is the primary
    # serialising guard between two webhook deliveries for the SAME
    # owner; the refresh+recheck of ``invoice.status`` below remains
    # as belt-and-suspenders so the loser of any race observes
    # ``paid`` and returns idempotently without double-crediting.
    owner = (
        await session.execute(select(User).where(User.id == invoice.owner_id).with_for_update())
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


async def sweep_expired_invoices(session: AsyncSession) -> int:
    """Mark stale ``pending`` legacy ``Invoice`` rows as ``expired``.

    V5-B-7 — pre-fix, an ``Invoice(status=pending)`` row created by the
    legacy ``POST /api/payments/deposit`` (``manual_deposit``) sat in
    the table forever if the user never finished paying. Unlike the
    real CryptoBot wallet-deposit flow, these rows are placeholder
    invoices (the provider id is hand-stamped, not issued by
    CryptoBot), so the webhook side will never emit a state change for
    them. This sweep closes the loop the same way M-6 closed it for
    ``WalletDeposit``: every ``invoice_sweep_seconds`` the loop in
    :mod:`backend.app.main` runs us and we flip any ``pending`` row
    older than ``invoice_expiry_seconds`` to ``expired``. No balance
    is credited; the user can always create a fresh invoice if they
    actually want to pay.

    Uses ``with_for_update(skip_locked=True)`` so a concurrent sweep
    in a sibling worker doesn't double-flip rows. Returns the number
    of rows touched so the caller can log it.
    """
    expiry_seconds = int(settings.invoice_expiry_seconds)
    if expiry_seconds <= 0:
        return 0

    cutoff = utcnow() - timedelta(seconds=expiry_seconds)

    rows = (
        (
            await session.execute(
                select(Invoice)
                .where(
                    Invoice.status == InvoiceStatus.pending,
                    Invoice.created_at <= cutoff,
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
        row.status = InvoiceStatus.expired

    await session.commit()
    return len(rows)
