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

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
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
    AdminCommentUpdateIn,
    AdminReviewItemOut,
    AdminReviewUpsertIn,
    AdminServiceItemOut,
    AdminServiceUpdateIn,
)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin", limit=600, window=60))],
)


# --------------------------------------------------------------------- helpers


async def _service_to_out(session: AsyncSession, service: Service) -> AdminServiceItemOut:
    category = await session.get(Category, service.category_id)
    return AdminServiceItemOut(
        id=service.id,
        owner_id=service.owner_id,
        category_id=service.category_id,
        category_slug=category.slug if category else None,
        title=service.title,
        description=service.description,
        price=float(service.price),
        status=service.status.value,
        ban_reason=service.ban_reason,
        views=service.views,
        deals_count=service.deals_count,
        deposit=float(service.deposit),
        rating_manual=float(service.rating_manual) if service.rating_manual is not None else None,
        created_at=service.created_at,
    )


async def _review_to_out(session: AsyncSession, review: Review) -> AdminReviewItemOut:
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


async def _comment_to_out(session: AsyncSession, comment: ServiceComment) -> AdminCommentItemOut:
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


@router.get("/users/{user_id}/services", response_model=list[AdminServiceItemOut])
async def list_user_services(
    user_id: int,
    _admin: AdminUser,
    session: SessionDep,
) -> list[AdminServiceItemOut]:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    rows = (
        (
            await session.execute(
                select(Service)
                .where(Service.owner_id == user_id)
                .order_by(Service.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [await _service_to_out(session, s) for s in rows]


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

    if body.title is not None and body.title != service.title:
        before["title"] = service.title
        after["title"] = body.title
        service.title = body.title
    if body.description is not None and body.description != service.description:
        before["description"] = service.description
        after["description"] = body.description
        service.description = body.description
    if body.price is not None and float(body.price) != float(service.price):
        before["price"] = float(service.price)
        after["price"] = float(body.price)
        service.price = body.price
    if body.deposit is not None and float(body.deposit) != float(service.deposit):
        before["deposit"] = float(service.deposit)
        after["deposit"] = float(body.deposit)
        service.deposit = body.deposit
    if body.views is not None and body.views != service.views:
        before["views"] = service.views
        after["views"] = body.views
        service.views = body.views
    if body.deals_count is not None and body.deals_count != service.deals_count:
        before["deals_count"] = service.deals_count
        after["deals_count"] = body.deals_count
        service.deals_count = body.deals_count
    if body.clear_rating:
        if service.rating_manual is not None:
            before["rating_manual"] = float(service.rating_manual)
            after["rating_manual"] = None
            service.rating_manual = None
    elif body.rating_manual is not None:
        current = float(service.rating_manual) if service.rating_manual is not None else None
        if current != body.rating_manual:
            before["rating_manual"] = current
            after["rating_manual"] = body.rating_manual
            service.rating_manual = body.rating_manual
    if body.status is not None:
        try:
            new_status = ServiceStatus(body.status)
        except ValueError:
            raise HTTPException(400, "Неверный статус услуги")  # noqa: B904
        if service.status != new_status:
            before["status"] = service.status.value
            after["status"] = new_status.value
            service.status = new_status
    if body.ban_reason is not None and body.ban_reason != service.ban_reason:
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
    await session.refresh(service)
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
        "price": float(service.price),
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
    return {"deleted": True, "service_id": service_id}


# --------------------------------------------------------------------- reviews


@router.get("/users/{user_id}/reviews", response_model=list[AdminReviewItemOut])
async def list_user_reviews(
    user_id: int,
    _admin: AdminUser,
    session: SessionDep,
    direction: Annotated[str, Query(pattern="^(received|written)$")] = "received",
) -> list[AdminReviewItemOut]:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    if direction == "written":
        stmt = select(Review).where(Review.author_id == user_id)
    else:
        stmt = select(Review).where(Review.target_id == user_id)
    rows = (await session.execute(stmt.order_by(Review.created_at.desc()))).scalars().all()
    return [await _review_to_out(session, r) for r in rows]


@router.post("/reviews", response_model=AdminReviewItemOut, status_code=201)
async def create_review(
    body: AdminReviewUpsertIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminReviewItemOut:
    """Admin creates a review on behalf of a user.

    ``author_id`` and ``target_id`` are required and validated. If the
    pair already has a review for the same deal, we still create a new
    row — the platform's regular create endpoint enforces uniqueness,
    but admin operations are deliberately unrestricted for cleanup.
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
    await session.flush()

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
    await session.refresh(review)
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
    await session.refresh(review)
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
    await session.commit()
    return {"deleted": True, "review_id": review_id}


# --------------------------------------------------------------------- comments


@router.get("/users/{user_id}/comments", response_model=list[AdminCommentItemOut])
async def list_user_comments(
    user_id: int,
    _admin: AdminUser,
    session: SessionDep,
) -> list[AdminCommentItemOut]:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    rows = (
        (
            await session.execute(
                select(ServiceComment)
                .where(ServiceComment.author_id == user_id)
                .order_by(ServiceComment.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [await _comment_to_out(session, c) for c in rows]


@router.get("/services/{service_id}/comments", response_model=list[AdminCommentItemOut])
async def list_service_comments(
    service_id: int,
    _admin: AdminUser,
    session: SessionDep,
) -> list[AdminCommentItemOut]:
    service = await session.get(Service, service_id)
    if service is None:
        raise HTTPException(404, "Услуга не найдена")
    rows = (
        (
            await session.execute(
                select(ServiceComment)
                .where(ServiceComment.service_id == service_id)
                .order_by(ServiceComment.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [await _comment_to_out(session, c) for c in rows]


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
    if body.text is not None and body.text != comment.text:
        before["text"] = comment.text
        after["text"] = body.text
        comment.text = body.text
    if body.clear_rating:
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
    await session.refresh(comment)
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
    return {"deleted": True, "comment_id": comment_id}
