from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from ..deps import CurrentUser, SessionDep
from ..models import Notification, NotificationType
from ..schemas import NotificationCountersOut, NotificationOut

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    user: CurrentUser,
    session: SessionDep,
    type: str | None = Query(None),
):
    stmt = select(Notification).where(Notification.recipient_id == user.id)
    if type:
        try:
            type_enum = NotificationType(type)
            stmt = stmt.where(Notification.type == type_enum)
        except ValueError:
            pass
    stmt = stmt.order_by(Notification.created_at.desc()).limit(200)
    result = await session.execute(stmt)
    return [NotificationOut.model_validate(n, from_attributes=True) for n in result.scalars().all()]


@router.get("/counters", response_model=NotificationCountersOut)
async def get_counters(user: CurrentUser, session: SessionDep):
    base = select(func.count(Notification.id)).where(Notification.recipient_id == user.id)
    all_count = (await session.execute(base)).scalar() or 0
    unread = (await session.execute(base.where(Notification.is_read.is_(False)))).scalar() or 0

    deals = (
        await session.execute(base.where(Notification.type == NotificationType.deals))
    ).scalar() or 0
    deposits = (
        await session.execute(base.where(Notification.type == NotificationType.deposits))
    ).scalar() or 0
    system = (
        await session.execute(base.where(Notification.type == NotificationType.system))
    ).scalar() or 0

    return NotificationCountersOut(
        all=all_count,
        deals=deals,
        deposits=deposits,
        system=system,
        unread=unread,
    )


@router.get("/{notif_id}", response_model=NotificationOut)
async def get_notification(notif_id: int, user: CurrentUser, session: SessionDep):
    """Fetch a single notification by id.

    Used by the dedicated ``/notifications/:id`` detail page so the frontend
    can render the full body + payload (deep links into the related deal,
    deposit, etc) without scrolling the inbox list.
    """
    notif = await session.get(Notification, notif_id)
    if not notif or notif.recipient_id != user.id:
        raise HTTPException(404, "Уведомление не найдено")
    return NotificationOut.model_validate(notif, from_attributes=True)


@router.post("/{notif_id}/read")
async def mark_read(notif_id: int, user: CurrentUser, session: SessionDep):
    notif = await session.get(Notification, notif_id)
    if not notif or notif.recipient_id != user.id:
        raise HTTPException(404, "Уведомление не найдено")
    notif.is_read = True
    await session.commit()
    return {"ok": True}


@router.post("/read-all")
async def mark_all_read(user: CurrentUser, session: SessionDep):
    stmt = select(Notification).where(
        Notification.recipient_id == user.id,
        Notification.is_read.is_(False),
    )
    result = await session.execute(stmt)
    for n in result.scalars().all():
        n.is_read = True
    await session.commit()
    return {"ok": True}
