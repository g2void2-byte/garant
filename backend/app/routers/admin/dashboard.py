"""``GET /api/admin/dashboard`` — KPI counters for the admin home."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from ...deps import AdminUser, SessionDep
from ...models import Deal, DealStatus, Service, ServiceStatus, User
from ...rate_limit import rate_limit
from ...schemas import AdminDashboardOut
from ...time_utils import utcnow

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin", limit=600, window=60))],
)


@router.get("/dashboard", response_model=AdminDashboardOut)
async def dashboard(_admin: AdminUser, session: SessionDep) -> AdminDashboardOut:
    """Return aggregate counters for the admin home screen.

    All counts are *whole-database* — no per-page filtering. The query
    fans out to ~10 SELECT COUNT(*) calls; on a normal-sized board this
    completes in milliseconds.
    """
    now = utcnow()
    h24 = now - timedelta(hours=24)
    d7 = now - timedelta(days=7)
    m5 = now - timedelta(minutes=5)

    async def _count(stmt) -> int:
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)

    total_users = await _count(select(func.count()).select_from(User))
    new_users_24h = await _count(
        select(func.count()).select_from(User).where(User.created_at >= h24)
    )
    new_users_7d = await _count(select(func.count()).select_from(User).where(User.created_at >= d7))
    online_users_5min = await _count(
        select(func.count()).select_from(User).where(User.last_login_at >= m5)
    )
    total_deals = await _count(select(func.count()).select_from(Deal))
    open_deals = await _count(
        select(func.count())
        .select_from(Deal)
        .where(
            Deal.status.in_(
                [
                    DealStatus.pending_confirmation,
                    DealStatus.pending_payment,
                    DealStatus.in_progress,
                ]
            )
        )
    )
    open_arbitration = await _count(
        select(func.count()).select_from(Deal).where(Deal.status == DealStatus.arbitration)
    )
    total_services = await _count(select(func.count()).select_from(Service))
    active_services = await _count(
        select(func.count()).select_from(Service).where(Service.status == ServiceStatus.active)
    )
    banned_users = await _count(
        select(func.count()).select_from(User).where(User.is_banned.is_(True))
    )
    frozen_users = await _count(
        select(func.count()).select_from(User).where(User.is_frozen.is_(True))
    )
    admins = await _count(select(func.count()).select_from(User).where(User.is_admin.is_(True)))
    arbiters = await _count(select(func.count()).select_from(User).where(User.is_arbiter.is_(True)))
    vips = await _count(select(func.count()).select_from(User).where(User.is_vip.is_(True)))

    return AdminDashboardOut(
        total_users=total_users,
        new_users_24h=new_users_24h,
        new_users_7d=new_users_7d,
        online_users_5min=online_users_5min,
        total_deals=total_deals,
        open_deals=open_deals,
        open_arbitration=open_arbitration,
        total_services=total_services,
        active_services=active_services,
        banned_users=banned_users,
        frozen_users=frozen_users,
        admins=admins,
        arbiters=arbiters,
        vips=vips,
    )
