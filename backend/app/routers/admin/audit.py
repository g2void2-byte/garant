"""``/api/admin/audit`` \u2014 read-only viewer over ``admin_audit_log``.

Append-only by design; no mutation endpoints. Supports filter by
action / actor / target / date range.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from ...deps import AdminUser, SessionDep
from ...models import AdminAuditLog, User
from ...rate_limit import rate_limit
from ...schemas import AdminAuditLogListOut, AdminAuditLogOut

router = APIRouter(
    prefix="/api/admin/audit",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin", limit=600, window=60))],
)


def _to_out(log: AdminAuditLog, actor: User | None) -> AdminAuditLogOut:
    return AdminAuditLogOut(
        id=log.id,
        actor_id=log.actor_id,
        actor_username=actor.username if actor else None,
        action=log.action,
        target_type=log.target_type,
        target_id=log.target_id,
        reason=log.reason,
        payload=log.payload,
        ip=log.ip,
        created_at=log.created_at,
    )


@router.get("", response_model=AdminAuditLogListOut)
async def list_audit(
    _admin: AdminUser,
    session: SessionDep,
    action: str | None = Query(None),
    actor_id: int | None = Query(None),
    target_type: str | None = Query(None),
    target_id: int | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    stmt = select(AdminAuditLog, User).outerjoin(User, User.id == AdminAuditLog.actor_id)
    count_stmt = select(func.count()).select_from(AdminAuditLog)
    if action:
        stmt = stmt.where(AdminAuditLog.action == action)
        count_stmt = count_stmt.where(AdminAuditLog.action == action)
    if actor_id is not None:
        stmt = stmt.where(AdminAuditLog.actor_id == actor_id)
        count_stmt = count_stmt.where(AdminAuditLog.actor_id == actor_id)
    if target_type:
        stmt = stmt.where(AdminAuditLog.target_type == target_type)
        count_stmt = count_stmt.where(AdminAuditLog.target_type == target_type)
    if target_id is not None:
        stmt = stmt.where(AdminAuditLog.target_id == target_id)
        count_stmt = count_stmt.where(AdminAuditLog.target_id == target_id)
    if since is not None:
        stmt = stmt.where(AdminAuditLog.created_at >= since)
        count_stmt = count_stmt.where(AdminAuditLog.created_at >= since)
    if until is not None:
        stmt = stmt.where(AdminAuditLog.created_at <= until)
        count_stmt = count_stmt.where(AdminAuditLog.created_at <= until)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(AdminAuditLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return AdminAuditLogListOut(
        items=[_to_out(log, actor) for log, actor in rows],
        total=int(total),
        page=page,
        page_size=page_size,
    )
