from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from utils.database.extras import WebDB
from utils.database.models import Users
from webapp.backend.deps import get_current_user
from webapp.backend.schemas import SupportPerson

router = APIRouter(prefix="/api/support", tags=["support"])


@router.get("/admins", response_model=list[SupportPerson])
async def admins(_: Users = Depends(get_current_user)) -> list[SupportPerson]:
    rows = await run_in_threadpool(WebDB().list_support, "admins")
    return [SupportPerson(**row) for row in rows]


@router.get("/arbiters", response_model=list[SupportPerson])
async def arbiters(_: Users = Depends(get_current_user)) -> list[SupportPerson]:
    rows = await run_in_threadpool(WebDB().list_support, "arbiters")
    return [SupportPerson(**row) for row in rows]
