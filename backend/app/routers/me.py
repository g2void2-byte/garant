from __future__ import annotations

from fastapi import APIRouter

from ..deps import CurrentUser, SessionDep
from ..models import Forum
from ..schemas import ForumOut, UserOut, UserUpdate

router = APIRouter(prefix="/api/me", tags=["me"])


def _user_out(user, deposit: float = 0, deals_sum: float = 0) -> UserOut:
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
        deals_sum=deals_sum,
        online=True,
        forums=[ForumOut(name=f.name, url=f.url) for f in user.forums],
    )


@router.get("", response_model=UserOut)
async def get_me(user: CurrentUser):
    return _user_out(user)


@router.patch("", response_model=UserOut)
async def update_me(body: UserUpdate, user: CurrentUser, session: SessionDep):
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.description is not None:
        user.description = body.description
    if body.banner_url is not None:
        user.banner_url = body.banner_url or None
    if body.photo_url is not None:
        user.photo_url = body.photo_url or None
    if body.forums is not None:
        for f in list(user.forums):
            await session.delete(f)
        for fd in body.forums:
            session.add(Forum(owner_id=user.id, name=fd.name, url=fd.url))
    await session.commit()
    await session.refresh(user)
    return _user_out(user)
