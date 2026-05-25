from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case, func, or_, select, update

from ..deps import CurrentUser, SessionDep
from ..models import Notification, NotificationType
from ..rate_limit import RLMarkAllRead
from ..schemas import NotificationCountersOut, NotificationOut
from ..ws import manager as ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

# page size matches the previous unbounded ``limit(200)``
# behaviour so existing clients see no functional change.
_PAGE_SIZE = 200


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    user: CurrentUser,
    session: SessionDep,
    type: str | None = Query(None),
    # cursor pagination by ``(created_at, id)``. Two
    # rows can share a ``created_at`` (we INSERT in bulk on broadcast
    # fan-out), so the tuple is required to make the order strict —
    # otherwise pages would silently drop or duplicate rows. The
    # cursor is the ``(created_at, id)`` of the last row the client
    # already has; we return rows strictly older than that.
    before_created_at: str | None = Query(
        None,
        description="ISO-8601 timestamp from the last seen notification.",
    ),
    before_id: int | None = Query(
        None,
        description="Id from the last seen notification (must accompany before_created_at).",
        ge=1,
    ),
    limit: int = Query(_PAGE_SIZE, ge=1, le=_PAGE_SIZE),
):
    stmt = select(Notification).where(Notification.recipient_id == user.id)
    if type:
        try:
            type_enum = NotificationType(type)
            stmt = stmt.where(Notification.type == type_enum)
        except ValueError:
            # V11-L-15 — an unknown ``type`` filter used to be silently
            # swallowed; surface it as a structured ``debug`` event so
            # JSON-logger pipelines can spot a frontend typo / stale
            # client without raising the user-visible status (the API
            # contract is "unknown filter = no filter"). ``type`` is
            # client-supplied but ``NotificationType`` is a closed enum,
            # so cardinality is fine to index.
            logger.debug(
                "notifications list: unknown type filter %r — falling back to no filter",
                type,
                extra={
                    "event": "notifications.list.unknown_type_filter",
                    "user_id": user.id,
                    "filter_type": type,
                },
            )
    if (before_created_at is None) != (before_id is None):
        # Keyset cursor must arrive as a ``(created_at, id)`` pair so
        # the ``OR``-form below stays strict; silently dropping the
        # half-specified case (the previous behaviour) hid frontend
        # encoding bugs by serving an unpaginated first page.
        raise HTTPException(
            400,
            "before_created_at и before_id должны передаваться вместе",
        )
    if before_created_at is not None and before_id is not None:
        try:
            cursor_ts = datetime.fromisoformat(before_created_at.replace("Z", "+00:00"))
        except ValueError:
            # V11-L-15 — cursor parse failures point at either a
            # frontend regression on keyset-pagination encoding or a
            # scraper passing garbage. Either way it's worth alerting
            # on. ``before_created_at`` itself isn't indexed in
            # ``extra`` (client-supplied strings → unbounded
            # cardinality); the boolean presence of a paired
            # ``before_id`` is.
            logger.warning(
                "notifications list: invalid before_created_at cursor",
                extra={
                    "event": "notifications.list.bad_cursor",
                    "user_id": user.id,
                    "before_id_present": before_id is not None,
                },
            )
            raise HTTPException(400, "Invalid before_created_at")  # noqa: B904
        # Standard keyset pagination: ``(created_at, id) < (cursor_ts,
        # cursor_id)`` in descending order. The OR-form avoids the
        # need for ``tuple_`` row-value support across all dialects
        # while remaining index-friendly.
        stmt = stmt.where(
            or_(
                Notification.created_at < cursor_ts,
                (Notification.created_at == cursor_ts) & (Notification.id < before_id),
            )
        )
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
    result = await session.execute(stmt)
    return [NotificationOut.model_validate(n, from_attributes=True) for n in result.scalars().all()]


@router.get("/counters", response_model=NotificationCountersOut)
async def get_counters(user: CurrentUser, session: SessionDep):
    # Fold the 5 counters into one ``COUNT(...) FILTER (WHERE ...)``
    # aggregate (rendered by SQLAlchemy's ``func.count(case(...))``) so
    # the DB does a single index-scan on ``ix_notifications_recipient_id``
    # instead of five. Mirrors the same idiom already used by
    # ``admin/dashboard.py``. Wire payload is identical.
    row = (
        await session.execute(
            select(
                func.count().label("all"),
                func.count(case((Notification.is_read.is_(False), 1))).label("unread"),
                func.count(case((Notification.type == NotificationType.deals, 1))).label("deals"),
                func.count(case((Notification.type == NotificationType.deposits, 1))).label(
                    "deposits"
                ),
                func.count(case((Notification.type == NotificationType.system, 1))).label("system"),
            )
            .select_from(Notification)
            .where(Notification.recipient_id == user.id)
        )
    ).one()

    return NotificationCountersOut(
        all=int(row.all or 0),
        deals=int(row.deals or 0),
        deposits=int(row.deposits or 0),
        system=int(row.system or 0),
        unread=int(row.unread or 0),
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
    already_read = notif.is_read
    notif_type = notif.type.value
    notif.is_read = True
    await session.commit()
    if not already_read:
        await _publish_read(user.id, ids=[notif_id], all=False, type_=notif_type)
    return {"ok": True}


@router.post("/read-all")
async def mark_all_read(user: CurrentUser, session: SessionDep, _rl: RLMarkAllRead):
    # Capture the ids being flipped so the WS event below can carry a
    # precise list — the frontend uses it to splice ``is_read=true``
    # into its TanStack cache without invalidating the whole list.
    rows = (
        (
            await session.execute(
                select(Notification.id).where(
                    Notification.recipient_id == user.id,
                    Notification.is_read.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )
    if rows:
        await session.execute(
            update(Notification)
            .where(
                Notification.recipient_id == user.id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True)
        )
        await session.commit()
        await _publish_read(user.id, ids=list(rows), all=True, type_=None)
    return {"ok": True}


async def _publish_read(
    recipient_id: int,
    *,
    ids: list[int],
    all: bool,
    type_: str | None,
) -> None:
    """Best-effort WS push of a ``notification.read`` cache-bust.

    Used by both ``mark_read`` and ``mark_all_read`` so a tab open on
    another device flips the notification list / counters without
    waiting for the next 30-second poll. Failures are swallowed and
    logged — a missing socket or a Redis publish error must never
    bubble up and turn a successful state mutation into a 500.
    """
    try:
        await ws_manager.publish(
            recipient_id,
            {
                "event": "notification.read",
                "data": {"ids": ids, "all": all, "type": type_},
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "notification.read publish failed for recipient_id=%s",
            recipient_id,
            extra={
                "event": "notifications.read.publish.failed",
                "recipient_id": recipient_id,
                "ids_count": len(ids),
            },
        )
