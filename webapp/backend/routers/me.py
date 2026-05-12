from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from utils.database.extras import WebDB
from utils.database.models import Users
from webapp.backend.deps import get_current_user
from webapp.backend.schemas import MeOut, ProfileUpdate

router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("", response_model=MeOut)
async def read_me(user: Users = Depends(get_current_user)) -> MeOut:
    data = await run_in_threadpool(WebDB().get_user_card_aggregate, user)
    return MeOut(**data)


@router.patch("", response_model=MeOut)
async def update_me(payload: ProfileUpdate, user: Users = Depends(get_current_user)) -> MeOut:
    web = WebDB()
    if payload.description is not None:
        await run_in_threadpool(web.set_profile_description, user.username, payload.description)
    if payload.banner_url is not None:
        await run_in_threadpool(web.set_profile_banner, user.username, payload.banner_url)
    if payload.forums is not None:
        await run_in_threadpool(web.set_profile_forums, user.username, payload.forums)
    data = await run_in_threadpool(web.get_user_card_aggregate, user)
    return MeOut(**data)
