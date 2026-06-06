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

import asyncio
import html
import logging
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.exc import SQLAlchemyError

from ... import notifier
from ...admin_audit import log_admin_action
from ...admin_guard import TotpUser
from ...bot.notify import send_dm as bot_send_dm
from ...deps import AdminUser, SessionDep
from ...models import Broadcast, Notification, NotificationType, User
from ...rate_limit import rate_limit
from ...schemas import (
    AdminBroadcastCreateIn,
    AdminBroadcastListOut,
    AdminBroadcastOut,
    AdminBroadcastPreviewOut,
)
from ...time_utils import utcnow

logger = logging.getLogger(__name__)

# Audit §3.2 — chunk size for streaming the recipient set through the
# database. The notification insert per recipient is cheap, but holding
# 50K objects in one transaction (and committing them in a single
# statement) is what the audit flagged as an OOM hazard. 500 keeps
# each commit small and aligns with the ``H-4`` comment further down.
_CHUNK_SIZE = 500

# Audit §3.2 — bound the per-chunk Telegram DM fan-out. Telegram
# allows ~30 messages/second platform-wide; 16 in-flight calls keeps
# us comfortably under that ceiling while still parallelising what
# used to be a one-at-a-time ``await bot_send_dm`` loop (worst-case
# ~3 minutes of HTTP latency for a 5K-recipient broadcast).
_DM_CONCURRENCY = 16

router = APIRouter(
    prefix="/api/admin/broadcasts",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin:broadcasts", limit=600, window=60))],
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
        # Audit §4.4 — the ``last_login_at >= since`` filter relies on a
        # btree index for selectivity at scale. ``users.last_login_at``
        # carries ``index=True`` in ``models.py`` (creating the SQLAlchemy
        # auto-name) and the supplementary migration
        # ``c8f4a2e91d35_pr_h_audit_refunded_indexes_softdelete`` adds
        # ``ix_users_last_login_at`` explicitly via ``CREATE INDEX
        # CONCURRENTLY`` so existing deployments pick it up without a
        # table-rewrite. Verified by ``test_audit_followup_all_simple
        # ::test_4_4_users_last_login_at_index_exists``.
        since = utcnow() - timedelta(days=body.audience_active_days)
        clauses.append(User.last_login_at >= since)
    if body.audience_min_deals is not None:
        clauses.append(User.deals_total >= body.audience_min_deals)
    # A-6 — temporal cohort. ``created_after`` is inclusive on the
    # boundary so an admin picking "users from 2026-01-01" includes
    # the row stamped at midnight. The audience builder treats the
    # window as half-open at the upper bound (``< created_before``)
    # to match the conventional "users before this date" reading.
    if body.audience_created_after is not None:
        clauses.append(User.created_at >= body.audience_created_after)
    if body.audience_created_before is not None:
        clauses.append(User.created_at < body.audience_created_before)
    # A-6 — language cohort. ``audience_language`` was lowercased by
    # the schema validator and ``users.language_code`` is stored
    # lowercased by ``deps._normalise_language_code``, so an
    # exact-match comparator is enough — no ``func.lower(...)``
    # wrapper needed, which keeps the existing ``ix_users_language_code``
    # btree usable.
    if body.audience_language is not None:
        clauses.append(User.language_code == body.audience_language)
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
        audience_created_after=b.audience_created_after,
        audience_created_before=b.audience_created_before,
        audience_language=b.audience_language,
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


def _audit_payload(
    body: AdminBroadcastCreateIn,
    *,
    total: int,
    delivered: int,
    failed: int,
) -> dict[str, Any]:
    return {
        "audience_role": body.audience_role,
        "audience_active_days": body.audience_active_days,
        "audience_min_deals": body.audience_min_deals,
        "audience_created_after": (
            body.audience_created_after.isoformat()
            if body.audience_created_after is not None
            else None
        ),
        "audience_created_before": (
            body.audience_created_before.isoformat()
            if body.audience_created_before is not None
            else None
        ),
        "audience_language": body.audience_language,
        "total_recipients": total,
        "delivered": delivered,
        "failed": failed,
    }


def _recipient_id_page_stmt(clause: Any, *, after_id: int, max_id: int):
    stmt = select(User.id).where(User.id > after_id, User.id <= max_id)
    if clause is not None:
        stmt = stmt.where(clause)
    return stmt.order_by(User.id).limit(_CHUNK_SIZE)


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

    # H-4: snapshot the recipient count and upper id bound before fan-out.
    stats_stmt = select(func.count(), func.coalesce(func.max(User.id), 0)).select_from(User)
    if clause is not None:
        stats_stmt = stats_stmt.where(clause)
    total_recipients_raw, max_user_id_raw = (await session.execute(stats_stmt)).one()
    total_recipients = int(total_recipients_raw)
    max_user_id = int(max_user_id_raw)

    # H-4 / audit §3.2: stream recipients in chunks. Audit §3.2 also
    # adds:
    # * a per-chunk ``session.commit()`` so the inserted notification
    #   rows never accumulate into one giant transaction (the previous
    #   shape kept all rows + their JSONB payloads in memory until the
    #   final commit, OOM-hazardous on 50K-recipient broadcasts);
    # * an ``asyncio.gather`` + semaphore for the Telegram DM fan-out
    #   inside each chunk, so 500 DMs go out in parallel instead of
    #   sequentially (worst-case shrinks from minutes to ~seconds).
    bcast = Broadcast(
        actor_id=admin.id,
        title=body.title,
        body=body.body,
        deeplink=body.deeplink,
        audience_role=body.audience_role,
        audience_active_days=body.audience_active_days,
        audience_min_deals=body.audience_min_deals,
        audience_created_after=body.audience_created_after,
        audience_created_before=body.audience_created_before,
        audience_language=body.audience_language,
        dispatch_inapp=body.dispatch_inapp,
        dispatch_dm=body.dispatch_dm,
        status="sending",
        total_recipients=total_recipients,
        delivered_count=0,
        failed_count=0,
    )
    session.add(bcast)
    await session.flush()
    await log_admin_action(
        session,
        actor=admin,
        action="broadcast.send.started",
        target_type="broadcast",
        target_id=bcast.id,
        payload=_audit_payload(body, total=total_recipients, delivered=0, failed=0),
        request=request,
    )
    await session.commit()

    delivered = 0
    failed = 0

    last_user_id = 0
    while True:
        page = await session.execute(
            _recipient_id_page_stmt(clause, after_id=last_user_id, max_id=max_user_id)
        )
        chunk_ids = list(page.scalars().all())
        if not chunk_ids:
            break
        last_user_id = int(chunk_ids[-1])

        chunk_stmt = select(User).where(User.id.in_(chunk_ids)).order_by(User.id)
        chunk_users = (await session.execute(chunk_stmt)).scalars().all()

        # Per-chunk buffers; nothing crosses the loop boundary.
        chunk_pending: list[tuple[Notification, dict[str, Any] | None]] = []
        chunk_dm_targets: list[tuple[User, str, bool]] = []
        chunk_delivered_without_dm = 0

        for u in chunk_users:
            try:
                delivered_via_inapp = False
                if body.dispatch_inapp:
                    notif, ws_payload = await notifier.insert(
                        session,
                        u.id,
                        NotificationType.system,
                        body.title or "Сообщение от администрации",
                        body.body,
                        {"deeplink": body.deeplink} if body.deeplink else None,
                    )
                    chunk_pending.append((notif, ws_payload))
                    delivered_via_inapp = True
                if body.dispatch_dm and u.tg_user_id:
                    title = body.title or "Сообщение от администрации"
                    dm_text = f"<b>{html.escape(title)}</b>\n\n{html.escape(body.body)}"
                    if body.deeplink:
                        href = html.escape(body.deeplink, quote=True)
                        text_part = html.escape(body.deeplink)
                        dm_text += f'\n\n<a href="{href}">{text_part}</a>'
                    chunk_dm_targets.append((u, dm_text, delivered_via_inapp))
                else:
                    # Either DM dispatch is off, or the user has no
                    # Telegram id. Only count the in-app fallback when
                    # that leg is actually enabled; a DM-only recipient
                    # without a usable Telegram id was not delivered.
                    if delivered_via_inapp:
                        chunk_delivered_without_dm += 1
                    else:
                        failed += 1
            except Exception:  # noqa: BLE001
                logger.exception(
                    "broadcast: delivery failed for user_id=%s",
                    u.id,
                    extra={
                        "event": "broadcast.delivery_failed",
                        "actor_id": admin.id,
                        "recipient_user_id": u.id,
                        "recipient_tg_user_id": u.tg_user_id,
                        "dispatch_inapp": bool(body.dispatch_inapp),
                        "dispatch_dm": bool(body.dispatch_dm),
                    },
                )
                failed += 1

        # Audit §3.2 — commit the chunk's notification inserts before
        # the WS publish + Telegram fan-out. WS / Redis / Telegram
        # latency must never hold a transaction open.
        await session.commit()

        for notif, ws_payload in chunk_pending:
            try:
                await notifier.dispatch_after_commit(session, notif, ws_payload)
            except (TimeoutError, SQLAlchemyError, OSError, RuntimeError):
                # Audit N-9 — narrowed from ``except Exception``. The
                # commit already succeeded; only delivery-time errors
                # (DB recipient lookup, WS/Redis publish, network)
                # should be swallowed. Programming bugs still propagate.
                logger.exception(
                    "broadcast: post-commit dispatch failed for notif id=%s",
                    notif.id,
                    extra={
                        "event": "broadcast.dispatch.failed",
                        "notif_id": notif.id,
                    },
                )

        delivered += chunk_delivered_without_dm

        if chunk_dm_targets:
            sem = asyncio.Semaphore(_DM_CONCURRENCY)
            actor_id = admin.id

            async def _send_dm(
                target_user: User,
                text: str,
                *,
                _sem: asyncio.Semaphore = sem,
                _actor_id: int = actor_id,
            ) -> bool:
                async with _sem:
                    try:
                        return bool(await bot_send_dm(target_user.tg_user_id, text))
                    except Exception:  # noqa: BLE001
                        # ``bot_send_dm`` already swallows the common
                        # ``TelegramAPIError`` cases and returns False,
                        # but a network-level failure still surfaces
                        # here; treat it the same as ``ok=False`` so
                        # the gather never raises and the chunk
                        # accounting stays consistent.
                        logger.exception(
                            "broadcast: DM dispatch failed for user_id=%s",
                            target_user.id,
                            extra={
                                "event": "broadcast.dm.failed",
                                "actor_id": _actor_id,
                                "recipient_user_id": target_user.id,
                                "recipient_tg_user_id": target_user.tg_user_id,
                            },
                        )
                        return False

            results = await asyncio.gather(*(_send_dm(u, t) for u, t, _ in chunk_dm_targets))
            for ok, (_, _, delivered_via_inapp) in zip(
                results,
                chunk_dm_targets,
                strict=True,
            ):
                if ok or delivered_via_inapp:
                    delivered += 1
                else:
                    failed += 1

        bcast.delivered_count = delivered
        bcast.failed_count = failed
        bcast.status = "sending"
        await session.commit()

    bcast.status = "sent"
    bcast.total_recipients = total_recipients
    bcast.delivered_count = delivered
    bcast.failed_count = failed
    bcast.sent_at = utcnow()
    await log_admin_action(
        session,
        actor=admin,
        action="broadcast.send.finished",
        target_type="broadcast",
        target_id=bcast.id,
        payload=_audit_payload(
            body,
            total=total_recipients,
            delivered=delivered,
            failed=failed,
        ),
        request=request,
    )
    await session.commit()
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
            .order_by(Broadcast.created_at.desc(), Broadcast.id.desc())
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
