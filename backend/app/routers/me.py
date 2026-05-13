from __future__ import annotations

from fastapi import APIRouter

from ..deps import CurrentUser, SessionDep
from ..models import Forum
from ..schemas import UserOut, UserUpdate
from ..serializers import user_to_out

router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("", response_model=UserOut)
async def get_me(user: CurrentUser):
    return user_to_out(user)


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
    if body.dm_deals is not None:
        user.dm_deals = body.dm_deals
    if body.dm_deposits is not None:
        user.dm_deposits = body.dm_deposits
    if body.dm_system is not None:
        user.dm_system = body.dm_system
    await session.commit()
    await session.refresh(user)
    return user_to_out(user)
