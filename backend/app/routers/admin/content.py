"""Admin content editing — services / reviews / comments.

Per spec, admins can:

* list / edit / delete a user's services (title, description, price,
  deposit, rating override, views, deals_count, status, ban_reason);
* list / edit / delete reviews (and create new reviews on behalf of any
  user — useful when migrating data or repairing a broken history);
* list / edit / delete service comments.

All mutations go through :func:`log_admin_action` so deletions remain
visible in the audit log even after the underlying row is gone. The
``payload`` JSON for delete actions captures the full row so the audit
remains a forensic source of truth.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...admin_audit import log_admin_action
from ...admin_guard import TotpUser
from ...deps import AdminUser, SessionDep
from ...models import (
    Category,
    Review,
    Service,
    ServiceComment,
    ServiceStatus,
    User,
)
from ...rate_limit import rate_limit
from ...schemas import (
    AdminCommentItemOut,
    AdminCommentListOut,
    AdminCommentUpdateIn,
    AdminReviewItemOut,
    AdminReviewListOut,
    AdminReviewUpsertIn,
    AdminServiceItemOut,
    AdminServiceListOut,
    AdminServiceUpdateIn,
)
from ...services import lock_user_for_rating, recompute_user_rating

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin:content", limit=600, window=60))],
)


# --------------------------------------------------------------------- helpers

# Audit 3.6 — the list endpoints below previously did per-row
# ``await session.get(User, ...)`` lookups inside ``_review_to_out`` /
# ``_comment_to_out`` / ``_service_to_out``, i.e. 1-2 extra SELECTs per
# returned row.  Batching the referenced rows into a single ``WHERE id
# IN (...)`` query and passing the resulting dict down to the
# serializer kills the N+1.  The single-row paths
# (create / update / delete) still pass ``None`` and fall back to the
# old ``session.get`` lookup — one extra round-trip there is cheap.


def _audit_decimal(value: object | None) -> str | None:
    if value is None:
        return None
    return str(Decimal(str(value)))


async def _users_by_id(session: AsyncSession, ids: set[int]) -> dict[int, User]:
    if not ids:
        return {}
    rows = (await session.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: u for u in rows}


async def _categories_by_id(session: AsyncSession, ids: set[int]) -> dict[int, Category]:
    if not ids:
        return {}
    rows = (await session.execute(select(Category).where(Category.id.in_(ids)))).scalars().all()
    return {c.id: c for c in rows}


async def _service_to_out(
    session: AsyncSession,
    service: Service,
    *,
    categories_by_id: dict[int, Category] | None = None,
) -> AdminServiceItemOut:
    if categories_by_id is not None:
        category = categories_by_id.get(service.category_id)
    else:
        category = await session.get(Category, service.category_id)
    return AdminServiceItemOut(
        id=service.id,
        owner_id=service.owner_id,
        category_id=service.category_id,
        category_slug=category.slug if category else None,
        title=service.title,
        description=service.description,
        price=Decimal(str(service.price)),
        status=service.status.value,
        ban_reason=service.ban_reason,
        views=service.views,
        deals_count=service.deals_count,
        deposit=Decimal(str(service.deposit)),
        rating_manual=(
            Decimal(str(service.rating_manual)) if service.rating_manual is not None else None
        ),
        created_at=service.created_at,
    )


async def _review_to_out(
    session: AsyncSession,
    review: Review,
    *,
    users_by_id: dict[int, User] | None = None,
) -> AdminReviewItemOut:
    if users_by_id is not None:
        author = users_by_id.get(review.author_id)
        target = users_by_id.get(review.target_id)
    else:
        author = await session.get(User, review.author_id)
        target = await session.get(User, review.target_id)
    return AdminReviewItemOut(
        id=review.id,
        deal_id=review.deal_id,
        author_id=review.author_id,
        author_username=author.username if author else None,
        target_id=review.target_id,
        target_username=target.username if target else None,
        rating=review.rating,
        text=review.text,
        created_at=review.created_at,
    )


async def _comment_to_out(
    session: AsyncSession,
    comment: ServiceComment,
    *,
    users_by_id: dict[int, User] | None = None,
) -> AdminCommentItemOut:
    if users_by_id is not None:
        author = users_by_id.get(comment.author_id)
    else:
        author = await session.get(User, comment.author_id)
    return AdminCommentItemOut(
        id=comment.id,
        service_id=comment.service_id,
        author_id=comment.author_id,
        author_username=author.username if author else None,
        text=comment.text,
        rating=comment.rating,
        created_at=comment.created_at,
    )


# --------------------------------------------------------------------- services


@router.get("/users/{user_id}/services", response_model=AdminServiceListOut)
async def list_user_services(
    user_id: int,
    _admin: AdminUser,
    session: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> AdminServiceListOut:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    stmt = select(Service).where(Service.owner_id == user_id)
    total = (
        await session.execute(select(func.count(Service.id)).where(Service.owner_id == user_id))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(Service.created_at.desc(), Service.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    # Audit 3.6 — batch-load the referenced categories so we don't
    # ``await session.get(Category, ...)`` once per service row.
    categories_by_id = await _categories_by_id(session, {s.category_id for s in rows})
    items = [await _service_to_out(session, s, categories_by_id=categories_by_id) for s in rows]
    return AdminServiceListOut(
        items=items,
        total=int(total),
        page=page,
        page_size=page_size,
    )


@router.post("/services/{service_id}", response_model=AdminServiceItemOut)
async def update_service(
    service_id: int,
    body: AdminServiceUpdateIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminServiceItemOut:
    service = await session.get(Service, service_id)
    if service is None:
        raise HTTPException(404, "Услуга не найдена")

    before: dict = {}
    after: dict = {}
    requested_fields = body.model_fields_set

    if body.title is not None and body.title != service.title:
        before["title"] = service.title
        after["title"] = body.title
        service.title = body.title
    if body.description is not None and body.description != service.description:
        before["description"] = service.description
        after["description"] = body.description
        service.description = body.description
    # Audit 3.7 — compare ``Decimal`` values directly. The previous
    # ``float(body.price) != float(service.price)`` could collapse
    # last-satoshi differences for amounts > 1e15, surfacing a
    # false-positive "no change" or a spurious change. Keep the audit
    # payload Decimal-canonical too; JSON numbers would reintroduce a
    # lossy IEEE-754 hop in the forensic trail.
    if body.price is not None and body.price != service.price:
        before["price"] = _audit_decimal(service.price)
        after["price"] = _audit_decimal(body.price)
        service.price = body.price
    if body.deposit is not None and body.deposit != service.deposit:
        before["deposit"] = _audit_decimal(service.deposit)
        after["deposit"] = _audit_decimal(body.deposit)
        service.deposit = body.deposit
    if body.views is not None and body.views != service.views:
        before["views"] = service.views
        after["views"] = body.views
        service.views = body.views
    if body.deals_count is not None and body.deals_count != service.deals_count:
        before["deals_count"] = service.deals_count
        after["deals_count"] = body.deals_count
        service.deals_count = body.deals_count
    clear_rating_requested = body.clear_rating or (
        "rating_manual" in requested_fields and body.rating_manual is None
    )
    if clear_rating_requested:
        if service.rating_manual is not None:
            before["rating_manual"] = _audit_decimal(service.rating_manual)
            after["rating_manual"] = None
            service.rating_manual = None
    elif body.rating_manual is not None:
        # Audit 3.7 — Decimal-vs-Decimal compare and payload.
        if service.rating_manual != body.rating_manual:
            before["rating_manual"] = _audit_decimal(service.rating_manual)
            after["rating_manual"] = _audit_decimal(body.rating_manual)
            service.rating_manual = body.rating_manual
    if body.status is not None:
        try:
            new_status = ServiceStatus(body.status)
        except ValueError:
            # V11-L-15 — surface invalid ServiceStatus tokens as a
            # structured event so an admin-UI regression that ships
            # an unknown status string is visible in JSON-logger
            # pipelines, not just a 400 in the browser console.
            # ``body.status`` is client-supplied, but ``ServiceStatus``
            # is a closed enum so its complement (unknown values) is
            # naturally bounded.
            logger.warning(
                "admin service.edit: invalid status %r",
                body.status,
                extra={
                    "event": "admin.service.update.invalid_status",
                    "actor_id": admin.id,
                    "service_id": service.id,
                    "requested_status": body.status,
                },
            )
            raise HTTPException(400, "Неверный статус услуги")  # noqa: B904
        if service.status != new_status:
            before["status"] = service.status.value
            after["status"] = new_status.value
            service.status = new_status
            if (
                new_status != ServiceStatus.banned
                and "ban_reason" not in requested_fields
                and service.ban_reason is not None
            ):
                before["ban_reason"] = service.ban_reason
                after["ban_reason"] = None
                service.ban_reason = None
    if "ban_reason" in requested_fields and body.ban_reason != service.ban_reason:
        before["ban_reason"] = service.ban_reason
        after["ban_reason"] = body.ban_reason
        service.ban_reason = body.ban_reason

    if not after:
        return await _service_to_out(session, service)

    await log_admin_action(
        session,
        actor=admin,
        action="service.edit",
        target_type="service",
        target_id=service.id,
        reason=None,
        payload={"before": before, "after": after, "owner_id": service.owner_id},
        request=request,
    )
    await session.commit()
    # V11-L-15 — paired with the audit-log row written above, this
    # gives ops a real-time signal on admin mutations without
    # querying the ``admin_audit_log`` table. ``changed_fields`` is
    # the closed set of column names from the schema; the actual
    # before/after values stay in the audit row only.
    logger.info(
        "admin service.edit ok",
        extra={
            "event": "admin.service.update.ok",
            "actor_id": admin.id,
            "service_id": service.id,
            "owner_id": service.owner_id,
            "changed_fields": sorted(after.keys()),
        },
    )
    return await _service_to_out(session, service)


@router.post("/services/{service_id}/delete", status_code=200)
async def delete_service(
    service_id: int,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> dict:
    service = await session.get(Service, service_id)
    if service is None:
        raise HTTPException(404, "Услуга не найдена")

    # Also remove dependent comments. We do this inside the same
    # transaction as the delete + audit so a partial failure rolls back.
    snapshot = {
        "id": service.id,
        "owner_id": service.owner_id,
        "title": service.title,
        "description": service.description,
        "price": _audit_decimal(service.price),
        "deposit": _audit_decimal(service.deposit),
        "rating_manual": _audit_decimal(service.rating_manual),
        "status": service.status.value,
    }
    await session.execute(
        ServiceComment.__table__.delete().where(ServiceComment.service_id == service.id)
    )

    await log_admin_action(
        session,
        actor=admin,
        action="service.delete",
        target_type="service",
        target_id=service.id,
        reason=None,
        payload=snapshot,
        request=request,
    )
    await session.delete(service)
    await session.commit()
    logger.info(
        "admin service.delete ok",
        extra={
            "event": "admin.service.delete.ok",
            "actor_id": admin.id,
            "service_id": service_id,
            "owner_id": snapshot["owner_id"],
        },
    )
    return {"deleted": True, "service_id": service_id}


# --------------------------------------------------------------------- reviews


@router.get("/users/{user_id}/reviews", response_model=AdminReviewListOut)
async def list_user_reviews(
    user_id: int,
    _admin: AdminUser,
    session: SessionDep,
    direction: Annotated[str, Query(pattern="^(received|written)$")] = "received",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> AdminReviewListOut:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    if direction == "written":
        stmt = select(Review).where(Review.author_id == user_id)
        count_stmt = select(func.count(Review.id)).where(Review.author_id == user_id)
    else:
        stmt = select(Review).where(Review.target_id == user_id)
        count_stmt = select(func.count(Review.id)).where(Review.target_id == user_id)
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(Review.created_at.desc(), Review.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    # Audit 3.6 — batch-load referenced users (author + target) so
    # the per-row ``session.get`` in ``_review_to_out`` collapses to
    # a single ``WHERE id IN (...)`` SELECT.
    user_ids: set[int] = set()
    for r in rows:
        user_ids.add(r.author_id)
        user_ids.add(r.target_id)
    users_by_id = await _users_by_id(session, user_ids)
    items = [await _review_to_out(session, r, users_by_id=users_by_id) for r in rows]
    return AdminReviewListOut(
        items=items,
        total=int(total),
        page=page,
        page_size=page_size,
    )


@router.post("/reviews", response_model=AdminReviewItemOut, status_code=201)
async def create_review(
    body: AdminReviewUpsertIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminReviewItemOut:
    """Admin creates a review on behalf of a user.

    ``author_id`` and ``target_id`` are required and validated. The
    UNIQUE constraint ``uq_reviews_author_deal`` (audit §1.1) binds
    admin writes too: an attempt to create a second review for the
    same ``(author_id, deal_id)`` pair is rejected with 409 instead
    of silently inflating the target's rating counters. Editing the
    existing row via ``POST /admin/content/reviews/{review_id}`` is
    the correct path for that case.
    """
    if body.author_id is None or body.target_id is None:
        raise HTTPException(400, "author_id и target_id обязательны")
    if body.author_id == body.target_id:
        raise HTTPException(400, "Автор и получатель должны различаться")
    for uid in (body.author_id, body.target_id):
        if await session.get(User, uid) is None:
            raise HTTPException(404, "Пользователь не найден")

    review = Review(
        author_id=body.author_id,
        target_id=body.target_id,
        deal_id=body.deal_id,
        rating=body.rating,
        text=body.text,
    )
    session.add(review)
    # Audit §1.1 — ``uq_reviews_author_deal`` rejects a duplicate
    # ``(author_id, deal_id)`` pair at flush time. Translate the
    # raw ``IntegrityError`` into a clean 409 so the admin UI gets a
    # usable message instead of a 500 stack trace.
    #
    # ``admin.id`` is snapshotted into a plain ``int`` *before* the
    # flush so the rejection logger never touches an expired ORM
    # attribute. Inside the ``except`` block the session is in
    # "must-rollback" state — a re-read of ``admin.id`` would fire a
    # synchronous SELECT (the ``_consume_totp`` upstream issued a
    # ``session.add(user)`` that nudges the attributes onto a
    # post-flush refresh path) and raise ``PendingRollbackError``
    # against the live request. Explicit ``session.rollback()`` is
    # left to the dep teardown; calling it here would expire
    # ``admin`` *after* the read which is the same race in reverse.
    actor_id = admin.id
    try:
        await session.flush()
    except IntegrityError as e:
        logger.warning(
            "admin review.create rejected: duplicate (author_id, deal_id)",
            extra={
                "event": "admin.review.create.duplicate",
                "actor_id": actor_id,
                "author_id": body.author_id,
                "target_id": body.target_id,
                "deal_id": body.deal_id,
            },
        )
        raise HTTPException(
            409,
            "Отзыв по этой сделке от данного автора уже существует",
        ) from e

    # Item 14 — keep ``target.good`` / ``target.bad`` in sync with the
    # ``reviews`` table the same way ``services.post_review`` does for
    # the regular user flow. Without this an admin-created review was
    # invisible on the affected user's profile (``reviews_count`` /
    # ``rating`` are derived from ``good + bad``).
    # Audit H-5 — lock the target row so an admin review-create that
    # lands concurrently with a user-side ``post_review`` for the same
    # target serialises through the same ``FOR UPDATE`` gate.
    target = await session.get(User, body.target_id)
    if target is not None:
        await lock_user_for_rating(session, target)
        await recompute_user_rating(session, target)

    await log_admin_action(
        session,
        actor=admin,
        action="review.create",
        target_type="review",
        target_id=review.id,
        reason=None,
        payload={
            "author_id": review.author_id,
            "target_id": review.target_id,
            "deal_id": review.deal_id,
            "rating": review.rating,
            "text": review.text,
        },
        request=request,
    )
    await session.commit()
    logger.info(
        "admin review.create ok",
        extra={
            "event": "admin.review.create.ok",
            "actor_id": admin.id,
            "review_id": review.id,
            "author_id": review.author_id,
            "target_id": review.target_id,
            "deal_id": review.deal_id,
        },
    )
    return await _review_to_out(session, review)


@router.post("/reviews/{review_id}", response_model=AdminReviewItemOut)
async def update_review(
    review_id: int,
    body: AdminReviewUpsertIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminReviewItemOut:
    review = await session.get(Review, review_id)
    if review is None:
        raise HTTPException(404, "Отзыв не найден")

    before: dict = {}
    after: dict = {}
    if review.rating != body.rating:
        before["rating"] = review.rating
        after["rating"] = body.rating
        review.rating = body.rating
    if review.text != body.text:
        before["text"] = review.text
        after["text"] = body.text
        review.text = body.text
    if not after:
        return await _review_to_out(session, review)
    # Item 14 — a rating change has to flow into the target's
    # ``good`` / ``bad`` counters. Recompute against the live reviews
    # table so the projection stays consistent regardless of which
    # direction the edit went (5→3, 2→4, etc.).
    # Audit H-5 — lock the target row so the rating edit serialises
    # against concurrent ``post_review`` / admin review edits on the
    # same target.
    if "rating" in after:
        target = await session.get(User, review.target_id)
        if target is not None:
            await lock_user_for_rating(session, target)
            await recompute_user_rating(session, target)
    await log_admin_action(
        session,
        actor=admin,
        action="review.edit",
        target_type="review",
        target_id=review.id,
        reason=None,
        payload={"before": before, "after": after},
        request=request,
    )
    await session.commit()
    logger.info(
        "admin review.edit ok",
        extra={
            "event": "admin.review.update.ok",
            "actor_id": admin.id,
            "review_id": review.id,
            "changed_fields": sorted(after.keys()),
        },
    )
    return await _review_to_out(session, review)


@router.post("/reviews/{review_id}/delete", status_code=200)
async def delete_review(
    review_id: int,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> dict:
    review = await session.get(Review, review_id)
    if review is None:
        raise HTTPException(404, "Отзыв не найден")

    snapshot = {
        "id": review.id,
        "author_id": review.author_id,
        "target_id": review.target_id,
        "deal_id": review.deal_id,
        "rating": review.rating,
        "text": review.text,
    }
    target_id = review.target_id
    await log_admin_action(
        session,
        actor=admin,
        action="review.delete",
        target_type="review",
        target_id=review.id,
        reason=None,
        payload=snapshot,
        request=request,
    )
    await session.delete(review)
    # Item 14 — dropping a review has to remove its contribution from
    # ``target.good`` / ``target.bad``. Flush first so the recompute's
    # aggregate ``SELECT`` sees the deletion.
    # Audit H-5 — same lock-then-recompute pattern as the create /
    # update paths above.
    await session.flush()
    target = await session.get(User, target_id)
    if target is not None:
        await lock_user_for_rating(session, target)
        await recompute_user_rating(session, target)
    await session.commit()
    logger.info(
        "admin review.delete ok",
        extra={
            "event": "admin.review.delete.ok",
            "actor_id": admin.id,
            "review_id": review_id,
            "author_id": snapshot["author_id"],
            "target_id": snapshot["target_id"],
        },
    )
    return {"deleted": True, "review_id": review_id}


# --------------------------------------------------------------------- comments


@router.get("/users/{user_id}/comments", response_model=AdminCommentListOut)
async def list_user_comments(
    user_id: int,
    _admin: AdminUser,
    session: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> AdminCommentListOut:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    stmt = select(ServiceComment).where(ServiceComment.author_id == user_id)
    total = (
        await session.execute(
            select(func.count(ServiceComment.id)).where(ServiceComment.author_id == user_id)
        )
    ).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(ServiceComment.created_at.desc(), ServiceComment.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    # Audit 3.6 — batch-load referenced authors; same one-SELECT-per
    # response shape as ``list_user_reviews`` above.
    users_by_id = await _users_by_id(session, {c.author_id for c in rows})
    items = [await _comment_to_out(session, c, users_by_id=users_by_id) for c in rows]
    return AdminCommentListOut(
        items=items,
        total=int(total),
        page=page,
        page_size=page_size,
    )


@router.get("/services/{service_id}/comments", response_model=AdminCommentListOut)
async def list_service_comments(
    service_id: int,
    _admin: AdminUser,
    session: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> AdminCommentListOut:
    service = await session.get(Service, service_id)
    if service is None:
        raise HTTPException(404, "Услуга не найдена")
    stmt = select(ServiceComment).where(ServiceComment.service_id == service_id)
    total = (
        await session.execute(
            select(func.count(ServiceComment.id)).where(ServiceComment.service_id == service_id)
        )
    ).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(ServiceComment.created_at.desc(), ServiceComment.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    # Audit 3.6 — batch-load referenced authors so per-row
    # ``session.get(User, ...)`` collapses to a single SELECT.
    users_by_id = await _users_by_id(session, {c.author_id for c in rows})
    items = [await _comment_to_out(session, c, users_by_id=users_by_id) for c in rows]
    return AdminCommentListOut(
        items=items,
        total=int(total),
        page=page,
        page_size=page_size,
    )


@router.post("/comments/{comment_id}", response_model=AdminCommentItemOut)
async def update_comment(
    comment_id: int,
    body: AdminCommentUpdateIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminCommentItemOut:
    comment = await session.get(ServiceComment, comment_id)
    if comment is None:
        raise HTTPException(404, "Комментарий не найден")

    before: dict = {}
    after: dict = {}
    requested_fields = body.model_fields_set
    if body.text is not None and body.text != comment.text:
        before["text"] = comment.text
        after["text"] = body.text
        comment.text = body.text
    clear_rating_requested = body.clear_rating or (
        "rating" in requested_fields and body.rating is None
    )
    if clear_rating_requested:
        if comment.rating is not None:
            before["rating"] = comment.rating
            after["rating"] = None
            comment.rating = None
    elif body.rating is not None and body.rating != comment.rating:
        before["rating"] = comment.rating
        after["rating"] = body.rating
        comment.rating = body.rating
    if not after:
        return await _comment_to_out(session, comment)
    await log_admin_action(
        session,
        actor=admin,
        action="comment.edit",
        target_type="comment",
        target_id=comment.id,
        reason=None,
        payload={"before": before, "after": after, "service_id": comment.service_id},
        request=request,
    )
    await session.commit()
    logger.info(
        "admin comment.edit ok",
        extra={
            "event": "admin.comment.update.ok",
            "actor_id": admin.id,
            "comment_id": comment.id,
            "service_id": comment.service_id,
            "changed_fields": sorted(after.keys()),
        },
    )
    return await _comment_to_out(session, comment)


@router.post("/comments/{comment_id}/delete", status_code=200)
async def delete_comment(
    comment_id: int,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> dict:
    comment = await session.get(ServiceComment, comment_id)
    if comment is None:
        raise HTTPException(404, "Комментарий не найден")
    snapshot = {
        "id": comment.id,
        "service_id": comment.service_id,
        "author_id": comment.author_id,
        "text": comment.text,
        "rating": comment.rating,
    }
    await log_admin_action(
        session,
        actor=admin,
        action="comment.delete",
        target_type="comment",
        target_id=comment.id,
        reason=None,
        payload=snapshot,
        request=request,
    )
    await session.delete(comment)
    await session.commit()
    logger.info(
        "admin comment.delete ok",
        extra={
            "event": "admin.comment.delete.ok",
            "actor_id": admin.id,
            "comment_id": comment_id,
            "service_id": snapshot["service_id"],
            "author_id": snapshot["author_id"],
        },
    )
    return {
        "deleted": True,
        "comment_id": comment_id,
        "service_id": snapshot["service_id"],
        "author_id": snapshot["author_id"],
    }
