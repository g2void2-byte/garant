"""``/api/admin/analytics`` \u2014 KPIs, time-series and top-lists.

Three endpoints, each backed by a small set of aggregate queries:

* ``GET /api/admin/analytics/kpi`` \u2014 dashboard counters (DAU/WAU/MAU,
  deals 24h/7d, volume 30d, open arbitration, pending withdrawals).
* ``GET /api/admin/analytics/series`` \u2014 30-day time series for deals
  count/volume, new users, deposits/withdrawals.
* ``GET /api/admin/analytics/top`` \u2014 top-10 sellers/buyers by
  completed-deal volume and top arbiters by resolution count.

We aggregate in Postgres via ``date_trunc('day', ...)`` so the API
returns at most ~30 points and the frontend doesn't have to bucket
client-side.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select

from ...deps import AdminUser, SessionDep
from ...models import (
    Deal,
    DealStatus,
    User,
    WalletDeposit,
    WalletDepositStatus,
    WalletWithdrawal,
    WalletWithdrawStatus,
)
from ...rate_limit import rate_limit
from ...schemas import (
    AdminAnalyticsKpiOut,
    AdminAnalyticsSeriesOut,
    AdminAnalyticsSeriesPoint,
    AdminAnalyticsTopListsOut,
    AdminAnalyticsTopUserOut,
)

router = APIRouter(
    prefix="/api/admin/analytics",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin", limit=600, window=60))],
)


_DONE_STATUSES = (
    DealStatus.completed,
    DealStatus.resolved_for_buyer,
    DealStatus.resolved_for_seller,
)


@router.get("/kpi", response_model=AdminAnalyticsKpiOut)
async def kpi(_admin: AdminUser, session: SessionDep):
    now = datetime.utcnow()
    h24 = now - timedelta(hours=24)
    d7 = now - timedelta(days=7)
    d30 = now - timedelta(days=30)

    async def _count(stmt) -> int:
        return int((await session.execute(stmt)).scalar_one() or 0)

    dau = await _count(select(func.count()).select_from(User).where(User.last_login_at >= h24))
    wau = await _count(select(func.count()).select_from(User).where(User.last_login_at >= d7))
    mau = await _count(select(func.count()).select_from(User).where(User.last_login_at >= d30))
    new_24h = await _count(select(func.count()).select_from(User).where(User.created_at >= h24))
    new_7d = await _count(select(func.count()).select_from(User).where(User.created_at >= d7))
    deals_24h = await _count(select(func.count()).select_from(Deal).where(Deal.created_at >= h24))
    deals_7d = await _count(select(func.count()).select_from(Deal).where(Deal.created_at >= d7))
    volume_30d = (
        await session.execute(
            select(func.coalesce(func.sum(Deal.amount), 0))
            .where(Deal.status.in_(_DONE_STATUSES))
            .where(Deal.completed_at >= d30)
        )
    ).scalar_one() or 0
    open_arb = await _count(
        select(func.count()).select_from(Deal).where(Deal.status == DealStatus.arbitration)
    )
    pending_wd = await _count(
        select(func.count())
        .select_from(WalletWithdrawal)
        .where(WalletWithdrawal.status == WalletWithdrawStatus.pending)
    )
    return AdminAnalyticsKpiOut(
        dau=dau,
        wau=wau,
        mau=mau,
        new_users_24h=new_24h,
        new_users_7d=new_7d,
        deals_24h=deals_24h,
        deals_7d=deals_7d,
        deals_volume_usd_30d=float(volume_30d),
        open_arbitration=open_arb,
        pending_withdrawals=pending_wd,
    )


async def _series(session, expr, start: datetime) -> list[AdminAnalyticsSeriesPoint]:
    """Run a single ``date_trunc('day', ts), count/sum`` query and pad missing days."""
    bucket, agg, table = expr
    rows = (
        await session.execute(
            select(func.date_trunc("day", bucket).label("d"), agg)
            .select_from(table)
            .where(bucket >= start)
            .group_by("d")
            .order_by("d")
        )
    ).all()
    by_day = {row[0].date().isoformat(): float(row[1] or 0) for row in rows if row[0]}
    out: list[AdminAnalyticsSeriesPoint] = []
    cursor = start.date()
    today = datetime.utcnow().date()
    while cursor <= today:
        out.append(
            AdminAnalyticsSeriesPoint(
                date=cursor.isoformat(), value=by_day.get(cursor.isoformat(), 0.0)
            )
        )
        cursor += timedelta(days=1)
    return out


@router.get("/series", response_model=AdminAnalyticsSeriesOut)
async def series(_admin: AdminUser, session: SessionDep):
    start = datetime.utcnow() - timedelta(days=30)
    deals_count = await _series(session, (Deal.created_at, func.count(), Deal), start)
    deals_volume = await _series(
        session,
        (
            Deal.completed_at,
            func.coalesce(
                func.sum(case((Deal.status.in_(_DONE_STATUSES), Deal.amount), else_=0)), 0
            ),
            Deal,
        ),
        start,
    )
    new_users = await _series(session, (User.created_at, func.count(), User), start)
    deposits = await _series(
        session,
        (
            WalletDeposit.paid_at,
            func.coalesce(
                func.sum(
                    case(
                        (WalletDeposit.status == WalletDepositStatus.paid, WalletDeposit.amount),
                        else_=0,
                    )
                ),
                0,
            ),
            WalletDeposit,
        ),
        start,
    )
    withdrawals = await _series(
        session,
        (
            WalletWithdrawal.processed_at,
            func.coalesce(
                func.sum(
                    case(
                        (
                            WalletWithdrawal.status == WalletWithdrawStatus.sent,
                            WalletWithdrawal.amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            WalletWithdrawal,
        ),
        start,
    )
    return AdminAnalyticsSeriesOut(
        deals_count_30d=deals_count,
        deals_volume_30d=deals_volume,
        new_users_30d=new_users,
        deposits_30d=deposits,
        withdrawals_30d=withdrawals,
    )


@router.get("/top", response_model=AdminAnalyticsTopListsOut)
async def top(_admin: AdminUser, session: SessionDep):
    top_sellers_rows = (
        await session.execute(
            select(
                User.id,
                User.username,
                User.display_name,
                func.coalesce(func.sum(Deal.amount), 0).label("v"),
            )
            .join(Deal, Deal.seller_id == User.id)
            .where(Deal.status.in_(_DONE_STATUSES))
            .group_by(User.id)
            .order_by(func.coalesce(func.sum(Deal.amount), 0).desc())
            .limit(10)
        )
    ).all()
    top_buyers_rows = (
        await session.execute(
            select(
                User.id,
                User.username,
                User.display_name,
                func.coalesce(func.sum(Deal.amount), 0).label("v"),
            )
            .join(Deal, Deal.buyer_id == User.id)
            .where(Deal.status.in_(_DONE_STATUSES))
            .group_by(User.id)
            .order_by(func.coalesce(func.sum(Deal.amount), 0).desc())
            .limit(10)
        )
    ).all()
    top_arbiters_rows = (
        await session.execute(
            select(
                User.id,
                User.username,
                User.display_name,
                func.count().label("v"),
            )
            .join(Deal, Deal.arbitration_resolved_by == User.id)
            .where(Deal.status.in_([DealStatus.resolved_for_buyer, DealStatus.resolved_for_seller]))
            .group_by(User.id)
            .order_by(func.count().desc())
            .limit(10)
        )
    ).all()

    return AdminAnalyticsTopListsOut(
        top_sellers=[
            AdminAnalyticsTopUserOut(
                user_id=r.id, username=r.username, display_name=r.display_name, value=float(r.v)
            )
            for r in top_sellers_rows
        ],
        top_buyers=[
            AdminAnalyticsTopUserOut(
                user_id=r.id, username=r.username, display_name=r.display_name, value=float(r.v)
            )
            for r in top_buyers_rows
        ],
        top_arbiters=[
            AdminAnalyticsTopUserOut(
                user_id=r.id, username=r.username, display_name=r.display_name, value=float(r.v)
            )
            for r in top_arbiters_rows
        ],
    )
