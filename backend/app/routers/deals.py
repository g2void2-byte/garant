from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, select

from ..deps import CurrentUser, PinUser, SessionDep
from ..models import Deal, DealStatus, User
from ..schemas import (
    DealArbitrationRequest,
    DealCancelRequest,
    DealCreate,
    DealOut,
    DealResolveRequest,
)
from ..services_deals import (
    accept_cancel,
    accept_deal,
    create_deal,
    decline_deal,
    finish_deal,
    request_cancel,
    resolve_arbitration,
    revoke_cancel,
    start_arbitration,
)

router = APIRouter(prefix="/api/deals", tags=["deals"])


def _deal_out(deal: Deal, user_id: int) -> DealOut:
    role = "buyer" if deal.buyer_id == user_id else "seller"
    currency_code = deal.currency.code if deal.currency else None

    return DealOut(
        id=deal.id,
        buyer=deal.buyer.username if deal.buyer else None,
        seller=deal.seller.username if deal.seller else None,
        sum=float(deal.amount if deal.amount is not None else deal.sum),
        description=deal.description,
        pay_comission=deal.pay_commission.value,
        status=deal.status.value,
        confirm_buyer=deal.confirm_buyer,
        confirm_seller=deal.confirm_seller,
        role=role,
        created_at=deal.created_at,
        currency_code=currency_code,
        amount=(float(deal.amount) if deal.amount is not None else None),
        commission_amount=(
            float(deal.commission_amount)
            if deal.commission_amount is not None
            else None
        ),
        in_progress_at=deal.in_progress_at,
        completed_at=deal.completed_at,
        cancellation_initiator=_role_for(deal, deal.cancellation_initiator_id),
        cancellation_reason=deal.cancellation_reason,
        cancellation_requested_at=deal.cancellation_requested_at,
        arbitration_initiator=_role_for(deal, deal.arbitration_initiator_id),
        arbitration_reason=deal.arbitration_reason,
        arbitration_resolved_by=(
            "admin"
            if deal.arbitration_resolved_by is not None
            else None
        ),
        arbitration_resolution=deal.arbitration_resolution,
        arbitration_resolved_at=deal.arbitration_resolved_at,
    )


def _role_for(deal: Deal, user_id: int | None) -> str | None:
    if user_id is None:
        return None
    if user_id == deal.buyer_id:
        return "buyer"
    if user_id == deal.seller_id:
        return "seller"
    return "other"


def _participant_or_admin(deal: Deal, user: User) -> None:
    if user.id in (deal.buyer_id, deal.seller_id):
        return
    if user.is_admin or user.is_arbiter:
        return
    raise HTTPException(403, "Доступ запрещён")


async def _get(session, deal_id: int) -> Deal:
    deal = await session.get(Deal, deal_id)
    if not deal:
        raise HTTPException(404, "Сделка не найдена")
    return deal


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
            stmt = stmt.where(Deal.status == DealStatus(status))
        except ValueError:
            pass
    stmt = stmt.order_by(Deal.created_at.desc())
    result = await session.execute(stmt)
    return [_deal_out(d, user.id) for d in result.scalars().all()]


@router.get("/{deal_id}", response_model=DealOut)
async def get_deal(deal_id: int, user: CurrentUser, session: SessionDep):
    deal = await _get(session, deal_id)
    _participant_or_admin(deal, user)
    return _deal_out(deal, user.id)


@router.post("", response_model=DealOut, status_code=201)
async def create_deal_endpoint(
    body: DealCreate, user: PinUser, session: SessionDep
):
    stmt = select(User).where(User.username == body.counterparty)
    result = await session.execute(stmt)
    counterparty = result.scalar_one_or_none()
    if not counterparty:
        raise HTTPException(404, "Пользователь не найден")
    if body.role == "buyer":
        buyer, seller = user, counterparty
    else:
        buyer, seller = counterparty, user

    try:
        deal = await create_deal(
            session,
            buyer,
            seller,
            body.currency_code,
            body.sum,
            body.description,
            body.pay_comission,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _deal_out(deal, user.id)


@router.post("/{deal_id}/accept", response_model=DealOut)
async def accept_deal_endpoint(
    deal_id: int, user: PinUser, session: SessionDep
):
    deal = await _get(session, deal_id)
    try:
        deal = await accept_deal(session, deal, user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _deal_out(deal, user.id)


@router.post("/{deal_id}/decline", response_model=DealOut)
async def decline_deal_endpoint(
    deal_id: int, user: PinUser, session: SessionDep
):
    deal = await _get(session, deal_id)
    try:
        deal = await decline_deal(session, deal, user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _deal_out(deal, user.id)


@router.post("/{deal_id}/finish", response_model=DealOut)
async def finish_deal_endpoint(
    deal_id: int, user: PinUser, session: SessionDep
):
    deal = await _get(session, deal_id)
    try:
        deal = await finish_deal(session, deal, user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _deal_out(deal, user.id)


@router.post("/{deal_id}/cancel_request", response_model=DealOut)
async def cancel_request_endpoint(
    deal_id: int,
    body: DealCancelRequest,
    user: PinUser,
    session: SessionDep,
):
    deal = await _get(session, deal_id)
    try:
        deal = await request_cancel(session, deal, user, body.reason)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _deal_out(deal, user.id)


@router.post("/{deal_id}/cancel_request/revoke", response_model=DealOut)
async def cancel_revoke_endpoint(
    deal_id: int, user: PinUser, session: SessionDep
):
    deal = await _get(session, deal_id)
    try:
        deal = await revoke_cancel(session, deal, user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _deal_out(deal, user.id)


@router.post("/{deal_id}/cancel_request/accept", response_model=DealOut)
async def cancel_accept_endpoint(
    deal_id: int, user: PinUser, session: SessionDep
):
    deal = await _get(session, deal_id)
    try:
        deal = await accept_cancel(session, deal, user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _deal_out(deal, user.id)


@router.post("/{deal_id}/debate", response_model=DealOut)
async def debate_endpoint(
    deal_id: int,
    body: DealArbitrationRequest,
    user: PinUser,
    session: SessionDep,
):
    deal = await _get(session, deal_id)
    try:
        deal = await start_arbitration(session, deal, user, body.reason)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _deal_out(deal, user.id)


@router.post("/{deal_id}/resolve", response_model=DealOut)
async def resolve_endpoint(
    deal_id: int,
    body: DealResolveRequest,
    user: PinUser,
    session: SessionDep,
):
    deal = await _get(session, deal_id)
    try:
        deal = await resolve_arbitration(session, deal, user, body.winner, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _deal_out(deal, user.id)
