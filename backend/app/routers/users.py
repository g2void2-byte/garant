from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ..deps import SessionDep
from ..models import User
from ..schemas import ForumOut, UserOut

router = APIRouter(prefix="/api/users", tags=["users"])


def _user_out(user: User) -> UserOut:
    reviews_count = user.good + user.bad
    total = reviews_count or 1
    rating = round(user.good / total * 5, 1)
    prefix = "admin" if user.is_admin else ("arbiter" if user.is_arbiter else None)
    return UserOut(
        id=user.id,
        user_id=user.tg_user_id,
        username=user.username or "",
        display_name=user.display_name,
        photo_url=user.photo_url,
        banner_url=user.banner_url,
        balance=float(user.balance),
        deposit=float(user.frozen_balance),
        description=user.description,
        prefix=prefix,
        is_admin=user.is_admin,
        is_arbiter=user.is_arbiter,
        admin=1 if user.is_admin else 0,
        good=user.good,
        bad=user.bad,
        rating=rating,
        reviews_count=reviews_count,
        deals_count=user.deals_total,
        deals_sum=0,
        online=True,
        forums=[ForumOut(name=f.name, url=f.url) for f in user.forums],
    )


@router.get("", response_model=list[UserOut])
async def list_users(
    session: SessionDep,
    q: str | None = Query(None),
    filter: str | None = Query(None),
):
    stmt = select(User)
    if q:
        stmt = stmt.where(
            User.username.ilike(f"%{q}%") | User.display_name.ilike(f"%{q}%")
        )
    if filter == "arbiters":
        stmt = stmt.where(User.is_arbiter.is_(True))
    elif filter == "admins":
        stmt = stmt.where(User.is_admin.is_(True))
    stmt = stmt.order_by(User.deals_total.desc()).limit(100)
    result = await session.execute(stmt)
    return [_user_out(u) for u in result.scalars().all()]


@router.get("/{username}", response_model=UserOut)
async def get_user(username: str, session: SessionDep):
    stmt = select(User).where(User.username == username)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    return _user_out(user)
