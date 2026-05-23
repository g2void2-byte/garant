from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, select

from ..deps import CurrentUser, PinUser, SessionDep
from ..models import Deal, DealStatus, User
from ..rate_limit import RLDealCreate
from ..schemas import (
    DealArbitrationRequest,
    DealCancelRequest,
    DealCreate,
    DealCreateWithTopup,
    DealCreateWithTopupOut,
    DealOut,
    DealResolveRequest,
    DealTopupInvoiceOut,
)
from ..services_deals import (
    InsufficientFundsError,
    accept_cancel,
    accept_deal,
    create_deal,
    create_deal_with_topup,
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
        buyer_photo_url=deal.buyer.photo_url if deal.buyer else None,
        seller_photo_url=deal.seller.photo_url if deal.seller else None,
        description=deal.description,
        status=deal.status.value,
        confirm_buyer=deal.confirm_buyer,
        confirm_seller=deal.confirm_seller,
        role=role,
        created_at=deal.created_at,
        currency_code=currency_code,
        amount=deal.amount,
        commission_amount=deal.commission_amount,
        in_progress_at=deal.in_progress_at,
        completed_at=deal.completed_at,
        cancellation_initiator=_role_for(deal, deal.cancellation_initiator_id),
        cancellation_reason=deal.cancellation_reason,
        cancellation_requested_at=deal.cancellation_requested_at,
        arbitration_initiator=_role_for(deal, deal.arbitration_initiator_id),
        arbitration_reason=deal.arbitration_reason,
        arbitration_resolved_by=("admin" if deal.arbitration_resolved_by is not None else None),
        arbitration_resolution=deal.arbitration_resolution,
        arbitration_resolved_at=deal.arbitration_resolved_at,
        payment_provider=deal.payment_provider or "cryptobot",
        topup_deposit_id=deal.topup_deposit_id,
        commission_paid=bool(deal.commission_paid),
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


async def _get_locked(session, deal_id: int) -> Deal:
    """Fetch a deal row with ``SELECT … FOR UPDATE``.

    Used by every mutation endpoint so two concurrent calls on the
    same deal can't both pass the status guard and double-spend the
    locked balance.
    """
    deal = (
        await session.execute(select(Deal).where(Deal.id == deal_id).with_for_update())
    ).scalar_one_or_none()
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
    stmt = select(Deal).where(or_(Deal.buyer_id == user.id, Deal.seller_id == user.id))
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
    body: DealCreate, user: PinUser, session: SessionDep, _rl: RLDealCreate
):
    # Audit C1 — every deal is initiated by the buyer, i.e. the caller
    # of this endpoint. The previous ``role="seller"`` branch let any
    # user lock an arbitrary counterparty's balance into an escrow row
    # they could not refuse: ``decline_deal`` / ``accept_deal`` are
    # seller-only, and ``sweep_inactivity`` only releases the lock after
    # ``inactivity_pending_confirmation_days``. The 10/min ``RLDealCreate``
    # didn't help — one accepted ``POST`` is enough to freeze the
    # victim's wallet for days. The schema-level ``Literal["buyer"]``
    # gate already rejects ``role="seller"`` with a 422, but we keep an
    # explicit defensive check here in case the schema is widened again.
    if body.role != "buyer":  # pragma: no cover — schema rejects it first
        raise HTTPException(400, "Создавать сделку может только покупатель")
    stmt = select(User).where(User.username == body.counterparty)
    result = await session.execute(stmt)
    counterparty = result.scalar_one_or_none()
    if not counterparty:
        raise HTTPException(404, "Пользователь не найден")
    buyer, seller = user, counterparty

    try:
        deal = await create_deal(
            session,
            buyer,
            seller,
            body.currency_code,
            body.amount,
            body.description,
            payment_provider=body.payment_provider,
        )
    except InsufficientFundsError as e:
        # Item 18 — structured payload so the frontend can render a
        # precise "не хватает X" hint instead of a generic toast. The
        # ``message`` field keeps the legacy human-readable string so
        # any client still treating ``detail`` as a string degrades
        # gracefully.
        raise HTTPException(
            400,
            detail={
                "code": "insufficient_funds",
                "message": str(e),
                "required": str(e.required),
                "balance": str(e.balance),
                "deficit": str(e.deficit),
                "currency_code": e.currency_code,
            },
        ) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _deal_out(deal, user.id)


@router.post(
    "/with-topup",
    response_model=DealCreateWithTopupOut,
    status_code=201,
)
async def create_deal_with_topup_endpoint(
    body: DealCreateWithTopup,
    user: PinUser,
    session: SessionDep,
    _rl: RLDealCreate,
):
    """P10 — create a deal funded by a deposit-invoice top-up.

    Replaces the balance-only :func:`create_deal_endpoint` for the
    happy-path frontend flow. The endpoint always issues a deposit
    invoice covering ``max(0, amount - buyer.balance) + commission``;
    the deal is born in :data:`DealStatus.pending_topup` and only
    advances to :data:`DealStatus.pending_confirmation` once the
    webhook lands a payment large enough to cover the principal.
    """
    if body.role != "buyer":  # pragma: no cover — schema rejects it first
        raise HTTPException(400, "Создавать сделку может только покупатель")
    stmt = select(User).where(User.username == body.counterparty)
    result = await session.execute(stmt)
    counterparty = result.scalar_one_or_none()
    if not counterparty:
        raise HTTPException(404, "Пользователь не найден")
    buyer, seller = user, counterparty

    try:
        deal, deposit = await create_deal_with_topup(
            session,
            buyer,
            seller,
            body.currency_code,
            body.amount,
            body.description,
            payment_provider=body.payment_provider,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    from decimal import Decimal as _Dec

    commission = _Dec(str(deal.commission_amount or 0))
    total = _Dec(str(deposit.amount))
    topup_principal = max(_Dec(0), total - commission)
    invoice = DealTopupInvoiceOut(
        deposit_id=deposit.id,
        pay_url=deposit.pay_url or "",
        total=total,
        topup_principal=topup_principal,
        commission=commission,
        currency_code=deposit.currency.code if deposit.currency else "",
        provider=(
            deposit.provider.value if hasattr(deposit.provider, "value") else str(deposit.provider)
        ),
        expires_at=None,
    )
    return DealCreateWithTopupOut(deal=_deal_out(deal, user.id), invoice=invoice)


@router.post("/{deal_id}/accept", response_model=DealOut)
async def accept_deal_endpoint(deal_id: int, user: PinUser, session: SessionDep):
    deal = await _get_locked(session, deal_id)
    try:
        deal = await accept_deal(session, deal, user)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _deal_out(deal, user.id)


@router.post("/{deal_id}/decline", response_model=DealOut)
async def decline_deal_endpoint(deal_id: int, user: PinUser, session: SessionDep):
    deal = await _get_locked(session, deal_id)
    try:
        deal = await decline_deal(session, deal, user)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _deal_out(deal, user.id)


@router.post("/{deal_id}/finish", response_model=DealOut)
async def finish_deal_endpoint(deal_id: int, user: PinUser, session: SessionDep):
    deal = await _get_locked(session, deal_id)
    try:
        deal = await finish_deal(session, deal, user)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _deal_out(deal, user.id)


@router.post("/{deal_id}/cancel_request", response_model=DealOut)
async def cancel_request_endpoint(
    deal_id: int,
    body: DealCancelRequest,
    user: PinUser,
    session: SessionDep,
):
    deal = await _get_locked(session, deal_id)
    try:
        deal = await request_cancel(session, deal, user, body.reason)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _deal_out(deal, user.id)


@router.post("/{deal_id}/cancel_request/revoke", response_model=DealOut)
async def cancel_revoke_endpoint(deal_id: int, user: PinUser, session: SessionDep):
    deal = await _get_locked(session, deal_id)
    try:
        deal = await revoke_cancel(session, deal, user)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _deal_out(deal, user.id)


@router.post("/{deal_id}/cancel_request/accept", response_model=DealOut)
async def cancel_accept_endpoint(deal_id: int, user: PinUser, session: SessionDep):
    deal = await _get_locked(session, deal_id)
    try:
        deal = await accept_cancel(session, deal, user)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _deal_out(deal, user.id)


@router.post("/{deal_id}/debate", response_model=DealOut)
async def debate_endpoint(
    deal_id: int,
    body: DealArbitrationRequest,
    user: PinUser,
    session: SessionDep,
):
    deal = await _get_locked(session, deal_id)
    try:
        deal = await start_arbitration(session, deal, user, body.reason)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _deal_out(deal, user.id)


@router.post("/{deal_id}/resolve", response_model=DealOut)
async def resolve_endpoint(
    deal_id: int,
    body: DealResolveRequest,
    user: PinUser,
    session: SessionDep,
):
    deal = await _get_locked(session, deal_id)
    try:
        deal = await resolve_arbitration(session, deal, user, body.winner, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _deal_out(deal, user.id)
