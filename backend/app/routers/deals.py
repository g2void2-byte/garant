"""Deal endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import current_user
from ..database import get_session
from ..models import Deal, DealStatus, User
from ..schemas import DealAction, DealCreate, DealOut
from ..services import (
    cancel_deal,
    confirm_deal,
    create_deal,
    fund_deal,
    open_dispute,
    resolve_counterparty,
)

router = APIRouter(prefix="/deals", tags=["deals"])


@router.get("", response_model=list[DealOut])
async def list_deals(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    status_filter: DealStatus | None = Query(default=None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
) -> list[Deal]:
    stmt = (
        select(Deal)
        .where(or_(Deal.buyer_id == user.id, Deal.seller_id == user.id))
        .order_by(Deal.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(Deal.status == status_filter)
    res = await session.execute(stmt)
    return list(res.scalars().unique().all())


@router.post("", response_model=DealOut)
async def create(
    body: DealCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Deal:
    counterparty = await resolve_counterparty(
        session,
        tg_id=body.counterparty_tg_id,
        username=body.counterparty_username,
    )
    deal = await create_deal(
        session,
        creator=user,
        counterparty=counterparty,
        role=body.role,
        title=body.title,
        description=body.description,
        amount=body.amount,
    )
    await session.commit()
    await session.refresh(deal)
    return deal


@router.get("/{deal_id}", response_model=DealOut)
async def get(
    deal_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Deal:
    res = await session.execute(select(Deal).where(Deal.id == deal_id))
    deal = res.scalar_one_or_none()
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deal not found")
    if user.id not in (deal.buyer_id, deal.seller_id) and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
    return deal


@router.post("/{deal_id}/action", response_model=DealOut)
async def act(
    deal_id: int,
    body: DealAction,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Deal:
    res = await session.execute(select(Deal).where(Deal.id == deal_id))
    deal = res.scalar_one_or_none()
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deal not found")
    if user.id not in (deal.buyer_id, deal.seller_id) and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")

    if body.action == "fund":
        await fund_deal(session, deal, user)
    elif body.action == "confirm":
        await confirm_deal(session, deal, user)
    elif body.action == "cancel":
        await cancel_deal(session, deal, user)
    elif body.action == "open_dispute":
        await open_dispute(session, deal, user, body.reason)
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported action")

    await session.commit()
    await session.refresh(deal)
    return deal
