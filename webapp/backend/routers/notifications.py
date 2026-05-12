from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from utils.database.extras import WebDB
from utils.database.models import Users
from webapp.backend.deps import get_current_user
from webapp.backend.schemas import NotificationCounters, NotificationOut

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: Users = Depends(get_current_user),
) -> list[NotificationOut]:
    rows = await run_in_threadpool(WebDB().list_notifications, user.username, type, limit, offset)
    return [NotificationOut(**row) for row in rows]


@router.get("/counters", response_model=NotificationCounters)
async def counters(user: Users = Depends(get_current_user)) -> NotificationCounters:
    data = await run_in_threadpool(WebDB().count_notifications, user.username)
    return NotificationCounters(**data)


@router.post("/{notification_id}/read")
async def mark_read(notification_id: int, user: Users = Depends(get_current_user)) -> dict:
    ok = await run_in_threadpool(WebDB().mark_notification_read, user.username, notification_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


@router.post("/read-all")
async def mark_all_read(user: Users = Depends(get_current_user)) -> dict:
    n = await run_in_threadpool(WebDB().mark_all_notifications_read, user.username)
    return {"ok": True, "updated": n}
