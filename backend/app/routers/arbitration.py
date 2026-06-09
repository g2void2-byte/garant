"""Arbitration endpoints.

Continental's TMA has a dedicated "Арбитраж" tab. Regular users see the
arbitration cases they're a party to; arbiters and admins see *every*
open / resolved arbitration so they can pick one up.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from ..deps import CurrentUser, SessionDep
from ..models import Deal, DealStatus
from ..routers.deals import _deal_out
from ..schemas import DealOut

router = APIRouter(prefix="/api/arbitration", tags=["arbitration"])


_ARBITRATION_STATES = (
    DealStatus.arbitration,
    DealStatus.resolved_for_buyer,
    DealStatus.resolved_for_seller,
)


@router.get("/deals", response_model=list[DealOut])
async def list_arbitration_deals(
    user: CurrentUser,
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    # eagerly load ``buyer`` / ``seller`` / ``currency``.  The
    # ``_deal_out`` projection reads ``deal.buyer.username``,
    # ``deal.seller.username`` and ``deal.currency.code`` for every
    # row; without ``selectinload`` the ORM emits an N+1 of three
    # extra SELECTs per deal.  Admins / arbiters routinely scroll the
    # full board (default ``limit=50``, max 200), so the pre-fix
    # cost was 3·N round-trips on a hot path that's only meant to
    # be one query plus one IN-load per relationship.
    stmt = (
        select(Deal)
        .where(Deal.status.in_(_ARBITRATION_STATES))
        .options(
            selectinload(Deal.buyer),
            selectinload(Deal.seller),
            selectinload(Deal.currency),
        )
    )
    if not (user.is_admin or user.is_arbiter):
        stmt = stmt.where(or_(Deal.buyer_id == user.id, Deal.seller_id == user.id))
    stmt = stmt.order_by(Deal.created_at.desc(), Deal.id.desc()).offset(offset).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return [_deal_out(d, user.id) for d in rows]
