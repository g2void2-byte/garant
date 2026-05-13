from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ..deps import CurrentUser, SessionDep
from ..models import Review, User
from ..schemas import ReviewCreate, ReviewOut
from ..services import post_review

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


def _review_out(r: Review) -> ReviewOut:
    return ReviewOut(
        id=r.id,
        deal_id=r.deal_id,
        author_username=r.author.username if r.author else None,
        target_username=r.target.username if r.target else None,
        rating=r.rating,
        text=r.text,
        created_at=r.created_at,
    )


@router.get("", response_model=list[ReviewOut])
async def list_reviews(session: SessionDep, user: str = Query(...)):
    stmt = (
        select(Review)
        .join(Review.target)
        .where(User.username == user)
        .order_by(Review.created_at.desc())
    )
    result = await session.execute(stmt)
    return [_review_out(r) for r in result.scalars().all()]


@router.post("", response_model=ReviewOut, status_code=201)
async def create_review(body: ReviewCreate, author: CurrentUser, session: SessionDep):
    stmt = select(User).where(User.username == body.target_username)
    result = await session.execute(stmt)
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Пользователь не найден")
    if target.id == author.id:
        raise HTTPException(400, "Нельзя оставить отзыв о себе")
    try:
        review = await post_review(
            session, author, target, body.rating, body.text, body.deal_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _review_out(review)
