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

from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
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

    Audit H-5 — pre-fix this helper SELECTed the aggregates and
    assigned them back to the ORM-managed ``target`` row WITHOUT a
    row lock on ``users.target_id``. Two concurrent ``post_review``
    calls could each see their own INSERT but not the other's, and
    both write the SAME value back, losing one review's contribution
    to the materialised counter. The underlying ``reviews`` table is
    still authoritative — but the public profile page reads
    ``good`` / ``bad`` directly off the row, so the counter lied.

    The fix is a single ``UPDATE users SET good = (SELECT ...), bad
    = (SELECT ...) WHERE id = :target_id``. Postgres takes a ROW
    lock on the target users row at the start of the UPDATE; under
    ``READ COMMITTED`` (our isolation level) a concurrent UPDATE
    that lands first causes the second UPDATE to wait and then
    re-read the row using the latest committed snapshot (EvalPlanQual
    semantics). The inner subselect inside the SET clause also
    re-evaluates against the latest snapshot — that is what
    guarantees the second writer's count includes the first writer's
    review.

    The caller is expected to have already locked the target row
    via :func:`lock_user_for_rating` (see ``post_review`` below) so
    the row-lock window covers the INSERT-then-recompute critical
    section; using a single-statement UPDATE on top is belt-and-
    braces against any future caller that forgets the explicit
    lock.

    We do NOT use the ORM ``target.good = …`` assignment any more
    because that's what produced the lost update: ORM dirty-track
    plus a stale Python-side count is exactly the read-modify-write
    cycle the race exploited.
    """
    good_expr = func.coalesce(func.sum(case((Review.rating >= 4, 1), else_=0)), 0)
    bad_expr = func.coalesce(func.sum(case((Review.rating <= 2, 1), else_=0)), 0)
    good_sub = select(good_expr).where(Review.target_id == target.id).scalar_subquery()
    bad_sub = select(bad_expr).where(Review.target_id == target.id).scalar_subquery()
    await session.execute(
        update(User).where(User.id == target.id).values(good=good_sub, bad=bad_sub)
    )
    # Refresh the in-session ORM object so callers that read
    # ``target.good`` / ``target.bad`` after this helper returns see
    # the values we just wrote (instead of the stale ORM cache).
    await session.refresh(target, attribute_names=["good", "bad"])


async def lock_user_for_rating(session: AsyncSession, target: User) -> None:
    """Acquire ``SELECT … FOR UPDATE`` on the target users row.

    Audit H-5 lock-order helper: callers that are about to insert a
    new ``reviews`` row and then call :func:`recompute_user_rating`
    should issue this lock first. The lock blocks any concurrent
    review-insert-then-recompute against the same target, so the
    materialised ``good`` / ``bad`` counters cannot suffer a
    lost-update race.

    Lock order intentionally matches the rest of the codebase:
    insert the *child* row (``Review``) first, then take FOR UPDATE
    on the *parent* row (``User``). Reviews never reference each
    other, so the child insert can never deadlock against the
    parent lock.
    """
    await session.execute(select(User.id).where(User.id == target.id).with_for_update())


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
    # Audit §1.1 — the SELECT above is a non-locking check-then-act
    # and two parallel callers can both observe ``existing is None``
    # before either INSERTs. The ``uq_reviews_author_deal`` UNIQUE
    # constraint on ``reviews(author_id, deal_id)`` makes the
    # racing INSERT abort here with ``IntegrityError``; we translate
    # it to the same ``ValueError`` the SELECT-guard raises so the
    # API surface (HTTP 400 + "Вы уже оставили отзыв по этой сделке")
    # stays consistent regardless of which side won the race. The
    # ``ValueError`` propagates to the FastAPI 400 handler in
    # ``routers/reviews.py``; the per-request session is rolled
    # back by the dep teardown, so we deliberately do NOT call
    # ``await session.rollback()`` here — doing so would expire the
    # ORM objects the router still reads (``author.id`` /
    # ``target.id``) and trigger a ``MissingGreenlet`` on the
    # synchronous attribute access in the router's logger.
    try:
        await session.flush()
    except IntegrityError as e:
        raise ValueError("Вы уже оставили отзыв по этой сделке") from e

    # Audit H-5 — lock the target users row so the INSERT-then-
    # recompute critical section serialises against any concurrent
    # ``post_review`` for the same target. Without this lock two
    # parallel ``post_review(target=X)`` calls could each see only
    # their own freshly-inserted review and both write the same
    # materialised counter back. ``recompute_user_rating`` is also
    # rewritten as a single-statement UPDATE-with-subselect for
    # defence-in-depth (see its docstring).
    await lock_user_for_rating(session, target)
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
