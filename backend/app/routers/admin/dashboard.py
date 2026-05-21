"""``GET /api/admin/dashboard`` — KPI counters for the admin home."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select

from ...deps import AdminUser, SessionDep
from ...models import Deal, DealStatus, Service, ServiceStatus, User
from ...rate_limit import rate_limit
from ...schemas import AdminDashboardOut
from ...time_utils import utcnow

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin:dashboard", limit=600, window=60))],
)


@router.get("/dashboard", response_model=AdminDashboardOut)
async def dashboard(_admin: AdminUser, session: SessionDep) -> AdminDashboardOut:
    """Return aggregate counters for the admin home screen.

    The 14 counters used to issue 14 separate ``SELECT COUNT(*)``
    statements. We now fold them into 3 single-row aggregate queries
    (users / deals / services) using ``COUNT(...) FILTER (WHERE ...)``
    (rendered by SQLAlchemy's ``func.count(case(...))``). The wire
    payload is identical; the DB does ~3 sequential scans + 11 in-row
    predicate checks instead of 14 separate scans.
    """
    now = utcnow()
    h24 = now - timedelta(hours=24)
    d7 = now - timedelta(days=7)
    m5 = now - timedelta(minutes=5)

    # ── users ────────────────────────────────────────────────────────
    #
    # ``case((cond, 1))`` returns 1 when the predicate matches and
    # ``NULL`` otherwise; ``count()`` ignores NULLs, so each expression
    # below counts only the rows that satisfy its condition. This is
    # the canonical PG idiom for "filtered counts in a single scan".
    users_row = (
        await session.execute(
            select(
                func.count().label("total"),
                func.count(case((User.created_at >= h24, 1))).label("new_24h"),
                func.count(case((User.created_at >= d7, 1))).label("new_7d"),
                func.count(case((User.last_login_at >= m5, 1))).label("online_5m"),
                func.count(case((User.is_banned.is_(True), 1))).label("banned"),
                func.count(case((User.is_frozen.is_(True), 1))).label("frozen"),
                func.count(case((User.is_admin.is_(True), 1))).label("admins"),
                func.count(case((User.is_arbiter.is_(True), 1))).label("arbiters"),
                func.count(case((User.is_vip.is_(True), 1))).label("vips"),
            ).select_from(User)
        )
    ).one()

    # ── deals ────────────────────────────────────────────────────────
    deals_row = (
        await session.execute(
            select(
                func.count().label("total"),
                func.count(
                    case(
                        (
                            # Audit M3 — ``pending_payment`` is reserved
                            # in ``DealStatus`` but no transition writes
                            # it, so counting it here was dead branch
                            # coverage that misled the dashboard.
                            Deal.status.in_(
                                [
                                    DealStatus.pending_confirmation,
                                    DealStatus.in_progress,
                                ]
                            ),
                            1,
                        )
                    )
                ).label("open"),
                func.count(case((Deal.status == DealStatus.arbitration, 1))).label("arbitration"),
            ).select_from(Deal)
        )
    ).one()

    # ── services ─────────────────────────────────────────────────────
    services_row = (
        await session.execute(
            select(
                func.count().label("total"),
                func.count(case((Service.status == ServiceStatus.active, 1))).label("active"),
            ).select_from(Service)
        )
    ).one()

    return AdminDashboardOut(
        total_users=int(users_row.total or 0),
        new_users_24h=int(users_row.new_24h or 0),
        new_users_7d=int(users_row.new_7d or 0),
        online_users_5min=int(users_row.online_5m or 0),
        total_deals=int(deals_row.total or 0),
        open_deals=int(deals_row.open or 0),
        open_arbitration=int(deals_row.arbitration or 0),
        total_services=int(services_row.total or 0),
        active_services=int(services_row.active or 0),
        banned_users=int(users_row.banned or 0),
        frozen_users=int(users_row.frozen or 0),
        admins=int(users_row.admins or 0),
        arbiters=int(users_row.arbiters or 0),
        vips=int(users_row.vips or 0),
    )
