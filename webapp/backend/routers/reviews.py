from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from utils.database.extras import WebDB
from utils.database.models import Users
from utils.notifier import notifier
from webapp.backend.deps import get_current_user
from webapp.backend.schemas import ReviewCreate, ReviewOut

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.get("", response_model=list[ReviewOut])
async def list_reviews(
    user: str = Query(..., alias="user"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: Users = Depends(get_current_user),
) -> list[ReviewOut]:
    rows = await run_in_threadpool(WebDB().list_reviews, user, limit, offset)
    return [ReviewOut(**row) for row in rows]


@router.post("", response_model=ReviewOut, status_code=201)
async def create_review(
    payload: ReviewCreate,
    user: Users = Depends(get_current_user),
) -> ReviewOut:
    target = payload.target_username.lstrip("@").lower()
    if target == user.username:
        raise HTTPException(status_code=400, detail="Cannot review yourself")
    row = await run_in_threadpool(
        WebDB().create_review,
        user.username,
        target,
        payload.rating,
        payload.text,
        payload.deal_id,
    )
    await notifier.push(
        target,
        type_="system",
        title="Новый отзыв",
        body=f"@{user.username} оставил(а) отзыв с оценкой {payload.rating}/5",
        payload={"review_id": row["id"]},
    )
    return ReviewOut(**row)
