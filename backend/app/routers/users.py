from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ..deps import SessionDep
from ..models import User
from ..schemas import UserOut
from ..serializers import user_to_out

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
async def list_users(
    session: SessionDep,
    q: str | None = Query(None),
    filter: str | None = Query(None),
):
    stmt = select(User)
    if q:
        stmt = stmt.where(User.username.ilike(f"%{q}%") | User.display_name.ilike(f"%{q}%"))
    if filter == "arbiters":
        stmt = stmt.where(User.is_arbiter.is_(True))
    elif filter == "admins":
        stmt = stmt.where(User.is_admin.is_(True))
    stmt = stmt.order_by(User.deals_total.desc()).limit(100)
    result = await session.execute(stmt)
    return [user_to_out(u) for u in result.scalars().all()]


@router.get("/{username}", response_model=UserOut)
async def get_user(username: str, session: SessionDep):
    stmt = select(User).where(User.username == username)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    return user_to_out(user)
