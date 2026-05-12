from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from utils.database.extras import WebDB
from utils.database.models import Users
from webapp.backend.deps import get_current_user
from webapp.backend.schemas import UserCard

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserCard])
async def list_users(
    q: str | None = Query(default=None),
    filter: str = Query(default="all"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: Users = Depends(get_current_user),
) -> list[UserCard]:
    rows = await run_in_threadpool(
        WebDB().list_users_with_aggregates, q, filter, limit, offset
    )
    return [UserCard(**row) for row in rows if row]


@router.get("/{username}", response_model=UserCard)
async def get_user(username: str, _: Users = Depends(get_current_user)) -> UserCard:
    data = await run_in_threadpool(WebDB().get_user_card_aggregate, username)
    if not data:
        raise HTTPException(status_code=404, detail="User not found")
    return UserCard(**data)
