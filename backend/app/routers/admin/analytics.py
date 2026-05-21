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

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select

from ...deps import AdminUser, SessionDep
from ...models import (
    Currency,
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
from ...time_utils import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/analytics",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin:analytics", limit=600, window=60))],
)


_DONE_STATUSES = (
    DealStatus.completed,
    DealStatus.resolved_for_buyer,
    DealStatus.resolved_for_seller,
)

# Financial KPIs (``deals_volume_usd_30d``, deposits/withdrawals
# time-series) are reported in a single currency so we don't naively
# sum BTC + ETH + USDT amounts as if they were comparable numbers.
# USDT is the canonical pegged-to-USD asset on CryptoBot, so we use
# it as the proxy for "dollar volume" in the dashboard. Deals and
# wallet rows in other currencies still appear in the count metrics
# but contribute zero to the volume sums.
_PRIMARY_CURRENCY_CODE = "USDT"


async def _primary_currency_id(session) -> int | None:
    """Return the ``currencies.id`` of the primary (USDT) row, or
    ``None`` if the seed never ran. Callers gate the financial sums on
    this so an unseeded DB produces zeros instead of mixed-currency
    garbage.

    V11-L-15 — when the seed is missing we emit a single structured
    ``warning`` per call so ops can distinguish "no financial data
    today" from "USDT row was deleted / migration failed". The event
    name is fixed so a Loki / Grafana alert can fire on a non-zero
    rate. We deliberately do NOT include the raw config value
    (``_PRIMARY_CURRENCY_CODE``) in ``extra`` beyond the constant
    above — the bounded string is fine to index.
    """
    cur_id = (
        await session.execute(select(Currency.id).where(Currency.code == _PRIMARY_CURRENCY_CODE))
    ).scalar_one_or_none()
    if cur_id is None:
        logger.warning(
            "admin analytics: primary currency %s not seeded — financial sums will be zero",
            _PRIMARY_CURRENCY_CODE,
            extra={
                "event": "admin.analytics.primary_currency_missing",
                "primary_currency_code": _PRIMARY_CURRENCY_CODE,
            },
        )
    return cur_id


@router.get("/kpi", response_model=AdminAnalyticsKpiOut)
async def kpi(_admin: AdminUser, session: SessionDep):
    now = utcnow()
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
    primary_cur_id = await _primary_currency_id(session)
    if primary_cur_id is not None:
        volume_stmt = (
            select(func.coalesce(func.sum(Deal.amount), 0))
            .where(Deal.status.in_(_DONE_STATUSES))
            .where(Deal.completed_at >= d30)
            .where(Deal.currency_id == primary_cur_id)
        )
        volume_30d = (await session.execute(volume_stmt)).scalar_one() or 0
    else:
        # No primary currency seeded — short-circuit in Python instead
        # of emitting a ``WHERE Deal.id IS NULL`` no-op query just to
        # force a zero scalar (the warning is already surfaced by
        # ``_primary_currency_id``).
        volume_30d = 0
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
    today = utcnow().date()
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
    start = utcnow() - timedelta(days=30)
    primary_cur_id = await _primary_currency_id(session)
    # Filter every financial sum to the primary currency (USDT) so we
    # never naively add BTC + ETH amounts. Count series (deals_count_30d,
    # new_users_30d) include every currency / row.
    cur_match = primary_cur_id if primary_cur_id is not None else -1
    deals_count = await _series(session, (Deal.created_at, func.count(), Deal), start)
    deals_volume = await _series(
        session,
        (
            Deal.completed_at,
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Deal.status.in_(_DONE_STATUSES)) & (Deal.currency_id == cur_match),
                            Deal.amount,
                        ),
                        else_=0,
                    )
                ),
                0,
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
                        (
                            (WalletDeposit.status == WalletDepositStatus.paid)
                            & (WalletDeposit.currency_id == cur_match),
                            WalletDeposit.amount,
                        ),
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
                            (WalletWithdrawal.status == WalletWithdrawStatus.sent)
                            & (WalletWithdrawal.currency_id == cur_match),
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
    primary_cur_id = await _primary_currency_id(session)
    cur_match = primary_cur_id if primary_cur_id is not None else -1
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
            .where(Deal.currency_id == cur_match)
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
            .where(Deal.currency_id == cur_match)
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
