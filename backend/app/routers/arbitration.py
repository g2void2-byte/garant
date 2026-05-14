"""Arbitration endpoints.

Continental's TMA has a dedicated "Арбитраж" tab. Regular users see the
arbitration cases they're a party to; arbiters and admins see *every*
open / resolved arbitration so they can pick one up.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import or_, select

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
    stmt = select(Deal).where(Deal.status.in_(_ARBITRATION_STATES))
    if not (user.is_admin or user.is_arbiter):
        stmt = stmt.where(or_(Deal.buyer_id == user.id, Deal.seller_id == user.id))
    stmt = stmt.order_by(Deal.created_at.desc()).offset(offset).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return [_deal_out(d, user.id) for d in rows]
