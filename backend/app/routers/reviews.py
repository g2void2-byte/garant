from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import func, select

from ..deps import CurrentUser, SessionDep
from ..models import Review, User
from ..rate_limit import RLReviewsList
from ..schemas import ReviewCreate, ReviewOut
from ..services import post_review

logger = logging.getLogger(__name__)

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
    response: Response,
    user: str = Query(...),
    limit: int = Query(50, ge=1, le=100),
    # cap ``offset`` at 10 000. Without an upper bound a
    # scraper could request ``offset=10_000_000`` and force Postgres
    # to walk the full review index just to skip rows we already
    # paged past. 10 000 rows is more reviews than any single profile
    # is realistically going to accumulate; anyone needing deeper
    # pagination should switch to a cursor-based API.
    offset: int = Query(0, ge=0, le=10_000),
):
    # Cap the page at 100 to avoid an attacker (or a misbehaving
    # client) walking every review on a popular profile in one shot.
    # ``useReviews`` now passes explicit pagination params; the default
    # still keeps older clients on the first bounded page.
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
    total = (
        await session.execute(
            select(func.count(Review.id)).where(Review.target_id == target.id)
        )
    ).scalar_one()
    response.headers["X-Total-Count"] = str(int(total))

    stmt = (
        select(Review)
        .where(Review.target_id == target.id)
        .order_by(Review.created_at.desc(), Review.id.desc())
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
        # V11-L-15 — surface the rejection reason as a structured event
        # so JSON-logger pipelines can spot a spike in "duplicate review"
        # / "deal not completed" / "not a party to the deal" failures
        # without grepping the message body. The free-text ``str(e)`` is
        # echoed to the client as the 400 body, so it adds no new PII
        # vs the existing access log line.
        logger.warning(
            "reviews create: rejected by post_review (%s)",
            e,
            extra={
                "event": "reviews.create.rejected",
                "author_id": author.id,
                "target_id": target.id,
                "deal_id": body.deal_id,
                "reason": str(e),
            },
        )
        raise HTTPException(400, str(e))  # noqa: B904
    await session.commit()
    return _review_out(review)
