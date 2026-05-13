from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, select

from ..deps import CurrentUser, SessionDep
from ..models import Deal, DealStatus, User
from ..schemas import DealCreate, DealOut
from ..services import arbitrate_deal, cancel_deal, complete_deal, confirm_deal, create_deal

router = APIRouter(prefix="/api/deals", tags=["deals"])


def _deal_out(deal: Deal, user_id: int) -> DealOut:
    role = "buyer" if deal.buyer_id == user_id else "seller"
    return DealOut(
        id=deal.id,
        buyer=deal.buyer.username if deal.buyer else None,
        seller=deal.seller.username if deal.seller else None,
        sum=float(deal.sum),
        description=deal.description,
        pay_comission=deal.pay_commission.value,
        status=deal.status.value,
        confirm_buyer=deal.confirm_buyer,
        confirm_seller=deal.confirm_seller,
        role=role,
        created_at=deal.created_at,
    )


@router.get("", response_model=list[DealOut])
async def list_deals(
    user: CurrentUser,
    session: SessionDep,
    role: str | None = Query(None),
    status: str | None = Query(None),
):
    stmt = select(Deal).where(
        or_(Deal.buyer_id == user.id, Deal.seller_id == user.id)
    )
    if role == "buyer":
        stmt = select(Deal).where(Deal.buyer_id == user.id)
    elif role == "seller":
        stmt = select(Deal).where(Deal.seller_id == user.id)
    if status:
        try:
            status_enum = DealStatus(status)
            stmt = stmt.where(Deal.status == status_enum)
        except ValueError:
            pass
    stmt = stmt.order_by(Deal.created_at.desc())
    result = await session.execute(stmt)
    return [_deal_out(d, user.id) for d in result.scalars().all()]


@router.get("/{deal_id}", response_model=DealOut)
async def get_deal(deal_id: int, user: CurrentUser, session: SessionDep):
    deal = await session.get(Deal, deal_id)
    if not deal:
        raise HTTPException(404, "Сделка не найдена")
    return _deal_out(deal, user.id)


@router.post("", response_model=DealOut, status_code=201)
async def create_deal_endpoint(body: DealCreate, user: CurrentUser, session: SessionDep):
    stmt = select(User).where(User.username == body.counterparty)
    result = await session.execute(stmt)
    counterparty = result.scalar_one_or_none()
    if not counterparty:
        raise HTTPException(404, "Пользователь не найден")

    if counterparty.id == user.id:
        raise HTTPException(400, "Нельзя создать сделку с самим собой")

    if body.role == "buyer":
        buyer, seller = user, counterparty
    else:
        buyer, seller = counterparty, user

    try:
        deal = await create_deal(
            session, buyer, seller, body.sum, body.description, body.pay_comission,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    return _deal_out(deal, user.id)


@router.post("/{deal_id}/confirm", response_model=DealOut)
async def confirm_deal_endpoint(deal_id: int, user: CurrentUser, session: SessionDep):
    deal = await session.get(Deal, deal_id)
    if not deal:
        raise HTTPException(404, "Сделка не найдена")
    try:
        deal = await confirm_deal(session, deal, user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _deal_out(deal, user.id)


@router.post("/{deal_id}/complete", response_model=DealOut)
async def complete_deal_endpoint(deal_id: int, user: CurrentUser, session: SessionDep):
    deal = await session.get(Deal, deal_id)
    if not deal:
        raise HTTPException(404, "Сделка не найдена")
    try:
        deal = await complete_deal(session, deal, user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _deal_out(deal, user.id)


@router.post("/{deal_id}/cancel", response_model=DealOut)
async def cancel_deal_endpoint(deal_id: int, user: CurrentUser, session: SessionDep):
    deal = await session.get(Deal, deal_id)
    if not deal:
        raise HTTPException(404, "Сделка не найдена")
    try:
        deal = await cancel_deal(session, deal, user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _deal_out(deal, user.id)


@router.post("/{deal_id}/arbitrate", response_model=DealOut)
async def arbitrate_deal_endpoint(
    deal_id: int,
    user: CurrentUser,
    session: SessionDep,
    reason: str = Query(""),
):
    deal = await session.get(Deal, deal_id)
    if not deal:
        raise HTTPException(404, "Сделка не найдена")
    try:
        deal = await arbitrate_deal(session, deal, user, reason)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _deal_out(deal, user.id)
