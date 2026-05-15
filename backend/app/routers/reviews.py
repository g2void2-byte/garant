from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ..deps import CurrentUser, SessionDep
from ..models import Review, User
from ..rate_limit import RLReviewsList
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
async def list_reviews(
    session: SessionDep,
    viewer: CurrentUser,
    _rl: RLReviewsList,
    user: str = Query(...),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    # Cap the page at 100 to avoid an attacker (or a misbehaving
    # client) walking every review on a popular profile in one shot.
    # The frontend's ``useReviews`` doesn't pass ``limit``/``offset``
    # yet — it receives the first 50 rows which is enough for the
    # current profile UI; pagination params let admins/tools page
    # through the rest without DoS-ing the DB.
    #
    # R7/H-12 — if the target has flipped ``is_hidden_profile`` we
    # return 404 to mirror ``GET /api/users/{username}``. The owner
    # themself (e.g. checking their own profile review feed) and
    # admins keep seeing the rows so a moderator can investigate
    # complaints without flipping the toggle.
    target = (await session.execute(select(User).where(User.username == user))).scalar_one_or_none()
    if target is None:
        raise HTTPException(404, "Пользователь не найден")
    if target.is_hidden_profile and not (viewer.is_admin or viewer.id == target.id):
        raise HTTPException(404, "Пользователь не найден")
    stmt = (
        select(Review)
        .where(Review.target_id == target.id)
        .order_by(Review.created_at.desc())
        .limit(limit)
        .offset(offset)
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
            session,
            author,
            target,
            body.rating,
            body.text,
            body.deal_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _review_out(review)
