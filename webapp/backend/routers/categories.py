from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from utils.database.extras import WebDB
from utils.database.models import Users
from webapp.backend.deps import get_current_user
from webapp.backend.schemas import CategoryOut

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("", response_model=list[CategoryOut])
async def list_categories(_: Users = Depends(get_current_user)) -> list[CategoryOut]:
    rows = await run_in_threadpool(WebDB().list_categories)
    return [CategoryOut(**row) for row in rows]
