from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from ..deps import SessionDep
from ..models import User
from ..schemas import SupportPersonOut

router = APIRouter(prefix="/api/support", tags=["support"])


def _person_out(user: User, prefix: str) -> SupportPersonOut:
    return SupportPersonOut(
        id=user.id,
        user_id=user.tg_user_id,
        username=user.username or "",
        display_name=user.display_name or (user.username or ""),
        photo_url=user.photo_url,
        admin=1 if user.is_admin else 0,
        prefix=prefix,
    )


@router.get("/admins", response_model=list[SupportPersonOut])
async def list_admins(session: SessionDep):
    stmt = select(User).where(User.is_admin.is_(True))
    result = await session.execute(stmt)
    return [_person_out(u, "admin") for u in result.scalars().all()]


@router.get("/arbiters", response_model=list[SupportPersonOut])
async def list_arbiters(session: SessionDep):
    stmt = select(User).where(User.is_arbiter.is_(True))
    result = await session.execute(stmt)
    return [_person_out(u, "arbiter") for u in result.scalars().all()]
