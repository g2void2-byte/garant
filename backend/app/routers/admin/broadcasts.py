"""``/api/admin/broadcasts`` \u2014 admin-authored notifications.

Two endpoints:

* ``POST /api/admin/broadcasts/preview`` \u2014 count the audience for
  the given filter without sending anything.
* ``POST /api/admin/broadcasts`` \u2014 send to that audience using the
  notifier (durable in ``notifications`` table + WS + optional DM).
* ``GET /api/admin/broadcasts`` \u2014 history with delivery counts.

The audience query is a single SQL filter so a 5K-user board sends in
sub-second; we don't fan out to ``len(users)`` row-by-row.
"""

from __future__ import annotations

import html
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, select

from ... import notifier
from ...admin_audit import log_admin_action
from ...admin_guard import TotpUser
from ...bot.notify import send_dm as bot_send_dm
from ...deps import AdminUser, SessionDep
from ...models import Broadcast, NotificationType, User
from ...rate_limit import rate_limit
from ...schemas import (
    AdminBroadcastCreateIn,
    AdminBroadcastListOut,
    AdminBroadcastOut,
    AdminBroadcastPreviewOut,
)
from ...time_utils import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/broadcasts",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin", limit=600, window=60))],
)


def _audience_filter(body: AdminBroadcastCreateIn):
    """Compose a SQLAlchemy WHERE clause from the audience filters."""
    clauses = []
    if body.audience_role == "admin":
        clauses.append(User.is_admin.is_(True))
    elif body.audience_role == "arbiter":
        clauses.append(User.is_arbiter.is_(True))
    elif body.audience_role == "vip":
        clauses.append(User.is_vip.is_(True))
    elif body.audience_role == "regular":
        clauses.append(
            and_(
                User.is_admin.is_(False),
                User.is_arbiter.is_(False),
                User.is_vip.is_(False),
            )
        )
    if body.audience_active_days is not None:
        since = utcnow() - timedelta(days=body.audience_active_days)
        clauses.append(User.last_login_at >= since)
    if body.audience_min_deals is not None:
        clauses.append(User.deals_total >= body.audience_min_deals)
    return and_(*clauses) if clauses else None


def _to_out(b: Broadcast, actor: User | None) -> AdminBroadcastOut:
    return AdminBroadcastOut(
        id=b.id,
        actor_id=b.actor_id,
        actor_username=actor.username if actor else None,
        title=b.title,
        body=b.body,
        deeplink=b.deeplink,
        audience_role=b.audience_role,
        audience_active_days=b.audience_active_days,
        audience_min_deals=b.audience_min_deals,
        dispatch_inapp=bool(b.dispatch_inapp),
        dispatch_dm=bool(b.dispatch_dm),
        status=b.status,
        total_recipients=b.total_recipients,
        delivered_count=b.delivered_count,
        failed_count=b.failed_count,
        scheduled_at=b.scheduled_at,
        sent_at=b.sent_at,
        created_at=b.created_at,
    )


@router.post("/preview", response_model=AdminBroadcastPreviewOut)
async def preview_audience(body: AdminBroadcastCreateIn, _admin: AdminUser, session: SessionDep):
    stmt = select(func.count()).select_from(User)
    clause = _audience_filter(body)
    if clause is not None:
        stmt = stmt.where(clause)
    total = (await session.execute(stmt)).scalar_one()
    return AdminBroadcastPreviewOut(total_recipients=int(total))


@router.post("", response_model=AdminBroadcastOut)
async def create_broadcast(
    body: AdminBroadcastCreateIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
):
    clause = _audience_filter(body)
    user_stmt = select(User)
    if clause is not None:
        user_stmt = user_stmt.where(clause)
    recipients = (await session.execute(user_stmt)).scalars().all()

    delivered = 0
    failed = 0
    for u in recipients:
        try:
            if body.dispatch_inapp:
                await notifier.push(
                    session,
                    u.id,
                    NotificationType.system,
                    body.title or "Сообщение от администрации",
                    body.body,
                    {"deeplink": body.deeplink} if body.deeplink else None,
                )
            if body.dispatch_dm and u.tg_user_id:
                # Comment 34 (audit v9): the Telegram bot is configured with
                # ``parse_mode=HTML`` (see ``bot.notify._bot``). Unescaped
                # angle brackets / ampersands in admin-authored copy made
                # the API reject the message with 400 ("can't parse entities").
                # ``html.escape`` keeps the wrapping ``<b>...</b>`` markup
                # intact while neutralising everything inside.
                title = body.title or "Сообщение от администрации"
                dm_text = f"<b>{html.escape(title)}</b>\n\n{html.escape(body.body)}"
                if body.deeplink:
                    dm_text += f"\n\n{html.escape(body.deeplink)}"
                ok = await bot_send_dm(u.tg_user_id, dm_text)
                if not ok:
                    # In-app counted as delivered; DM-only failure shouldn't
                    # negate that, but we record it as a partial failure.
                    failed += 1
                    continue
            delivered += 1
        except Exception:  # noqa: BLE001
            logger.exception("broadcast: delivery failed for user_id=%s", u.id)
            failed += 1

    bcast = Broadcast(
        actor_id=admin.id,
        title=body.title,
        body=body.body,
        deeplink=body.deeplink,
        audience_role=body.audience_role,
        audience_active_days=body.audience_active_days,
        audience_min_deals=body.audience_min_deals,
        dispatch_inapp=body.dispatch_inapp,
        dispatch_dm=body.dispatch_dm,
        status="sent",
        total_recipients=len(recipients),
        delivered_count=delivered,
        failed_count=failed,
        sent_at=utcnow(),
    )
    session.add(bcast)
    await session.flush()

    await log_admin_action(
        session,
        actor=admin,
        action="broadcast.send",
        target_type="broadcast",
        target_id=bcast.id,
        payload={
            "audience_role": body.audience_role,
            "audience_active_days": body.audience_active_days,
            "audience_min_deals": body.audience_min_deals,
            "total_recipients": len(recipients),
            "delivered": delivered,
            "failed": failed,
        },
        request=request,
    )
    await session.commit()
    await session.refresh(bcast)
    return _to_out(bcast, admin)


@router.get("", response_model=AdminBroadcastListOut)
async def list_broadcasts(
    _admin: AdminUser,
    session: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    # PR-H (L-10) — hide soft-deleted broadcasts from the list. The
    # row still exists so the admin audit log entry remains joinable.
    base_filter = Broadcast.deleted_at.is_(None)
    total = (
        await session.execute(select(func.count()).select_from(Broadcast).where(base_filter))
    ).scalar_one()
    rows = (
        await session.execute(
            select(Broadcast, User)
            .join(User, User.id == Broadcast.actor_id)
            .where(base_filter)
            .order_by(Broadcast.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return AdminBroadcastListOut(
        items=[_to_out(b, u) for b, u in rows],
        total=int(total),
        page=page,
        page_size=page_size,
    )


@router.delete("/{broadcast_id}")
async def delete_broadcast(
    broadcast_id: int,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
):
    b = await session.get(Broadcast, broadcast_id)
    if b is None or b.deleted_at is not None:
        # Already soft-deleted rows look like 404s to the admin UI;
        # the row stays for audit-log linkage but isn't a valid target.
        raise HTTPException(404, "Рассылка не найдена")
    # PR-H (L-10) — soft-delete instead of ``session.delete``. The
    # hard-delete used to orphan the matching ``admin_audit_log`` row
    # (the FK target vanished, so the action stayed on the audit
    # screen but its target was un-resolvable).
    b.deleted_at = utcnow()
    await log_admin_action(
        session,
        actor=admin,
        action="broadcast.delete",
        target_type="broadcast",
        target_id=broadcast_id,
        payload={"title": b.title},
        request=request,
    )
    await session.commit()
    return {"ok": True}
