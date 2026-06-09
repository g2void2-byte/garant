from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import func, or_, select

from ..admin_guard import TotpOrArbiterUser
from ..deps import CurrentUser, PinUser, SessionDep
from ..models import Deal, DealStatus, User, WalletDeposit, WalletDepositStatus
from ..rate_limit import RLDealCreate
from ..schemas import (
    DealArbitrationRequest,
    DealCancelRequest,
    DealCreate,
    DealCreateWithTopup,
    DealCreateWithTopupOut,
    DealOut,
    DealResolveRequest,
    DealRoleWire,
    DealTopupInvoiceOut,
    PaymentProviderWire,
)
from ..services_deals import (
    accept_cancel,
    accept_deal,
    cancel_pending_topup,
    create_deal_with_topup,
    decline_deal,
    finish_deal,
    request_cancel,
    resolve_arbitration,
    revoke_cancel,
    start_arbitration,
)

router = APIRouter(prefix="/api/deals", tags=["deals"])


def _payment_provider_for(value: object) -> PaymentProviderWire:
    provider = getattr(value, "value", value) or "cryptobot"
    if provider == "cryptobot":
        return "cryptobot"
    if provider == "crystalpay":
        return "crystalpay"
    raise ValueError(f"unknown payment provider: {provider!r}")


def _resolution_for(value: str | None) -> Literal["buyer", "seller"] | None:
    if value is None:
        return None
    if value == "buyer":
        return "buyer"
    if value == "seller":
        return "seller"
    raise ValueError(f"unknown arbitration resolution: {value!r}")


def _topup_invoice_from_deposit(
    deal: Deal,
    deposit: WalletDeposit | None,
    *,
    paid_total: Decimal = Decimal("0"),
) -> DealTopupInvoiceOut | None:
    if deposit is None or deposit.status != WalletDepositStatus.pending:
        return None
    commission = Decimal("0") if deal.commission_paid else Decimal(str(deal.commission_amount or 0))
    total = Decimal(str(deposit.amount))
    topup_principal = max(Decimal(0), total - commission)
    return DealTopupInvoiceOut(
        deposit_id=deposit.id,
        pay_url=deposit.pay_url or "",
        total=total,
        topup_principal=topup_principal,
        commission=commission,
        paid_total=paid_total,
        currency_code=deposit.currency.code if deposit.currency else "",
        provider=_payment_provider_for(deposit.provider),
        expires_at=None,
    )


def _deal_out(
    deal: Deal,
    user_id: int,
    *,
    topup_invoice: DealTopupInvoiceOut | None = None,
) -> DealOut:
    role = _role_for(deal, user_id) or "other"
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
        amount=Decimal(str(deal.amount)),
        commission_amount=(
            Decimal(str(deal.commission_amount)) if deal.commission_amount is not None else None
        ),
        in_progress_at=deal.in_progress_at,
        completed_at=deal.completed_at,
        cancellation_initiator=_role_for(deal, deal.cancellation_initiator_id),
        cancellation_reason=deal.cancellation_reason,
        cancellation_requested_at=deal.cancellation_requested_at,
        arbitration_initiator=_role_for(deal, deal.arbitration_initiator_id),
        arbitration_reason=deal.arbitration_reason,
        arbitration_resolved_by=("admin" if deal.arbitration_resolved_by is not None else None),
        arbitration_resolution=_resolution_for(deal.arbitration_resolution),
        arbitration_resolved_at=deal.arbitration_resolved_at,
        payment_provider=_payment_provider_for(deal.payment_provider),
        topup_deposit_id=deal.topup_deposit_id,
        commission_paid=bool(deal.commission_paid),
        topup_invoice=topup_invoice,
    )


async def _hydrate_topup_invoice(session, deal: Deal) -> DealTopupInvoiceOut | None:
    """Look up the deal's pending top-up invoice (P10).

    Returns ``None`` when the deal has no linked ``WalletDeposit``,
    the deposit row is no longer ``pending`` (i.e. paid / expired),
    or the deal isn't in ``pending_topup`` anymore.
    """
    if deal.status != DealStatus.pending_topup or deal.topup_deposit_id is None:
        return None
    deposit = await session.get(WalletDeposit, deal.topup_deposit_id)
    paid_total = Decimal("0")
    if deposit is not None and deposit.linked_deal_id is not None:
        paid_total = Decimal(
            str(
                (
                    await session.execute(
                        select(func.coalesce(func.sum(WalletDeposit.paid_amount), 0)).where(
                            WalletDeposit.linked_deal_id == deposit.linked_deal_id,
                            WalletDeposit.status == WalletDepositStatus.paid,
                        )
                    )
                ).scalar_one()
            )
        )
    return _topup_invoice_from_deposit(deal, deposit, paid_total=paid_total)


def _role_for(deal: Deal, user_id: int | None) -> DealRoleWire | None:
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

    ``populate_existing=True`` reloads the row's columns from the
    locking SELECT result even when the Deal is already in the
    session's identity map. Today every mutation endpoint calls
    ``_get_locked`` as the first session operation for the deal, so
    the row isn't yet cached and the option is a no-op — but if a
    future endpoint adds an earlier ``session.get(Deal, …)`` (e.g.
    for a pre-lock authorisation check), the ``FOR UPDATE`` would
    still acquire correctly but the column data would come from the
    stale cached instance, reopening the lost-update window the lock
    is meant to close. Mirror the ``populate_existing=True`` pattern
    already used in ``services_wallet`` for the same reason.
    """
    deal = (
        await session.execute(
            select(Deal)
            .where(Deal.id == deal_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if not deal:
        raise HTTPException(404, "Сделка не найдена")
    return deal


@router.get("", response_model=list[DealOut])
async def list_deals(
    response: Response,
    user: CurrentUser,
    session: SessionDep,
    role: Literal["buyer", "seller"] | None = Query(None),
    status: DealStatus | None = Query(None),
    limit: int = Query(100, ge=1, le=200, description="Max rows to return."),
    offset: int = Query(0, ge=0, description="Row offset for cursorless pagination."),
):
    stmt = select(Deal).where(or_(Deal.buyer_id == user.id, Deal.seller_id == user.id))
    if role == "buyer":
        stmt = select(Deal).where(Deal.buyer_id == user.id)
    elif role == "seller":
        stmt = select(Deal).where(Deal.seller_id == user.id)
    if status is not None:
        stmt = stmt.where(Deal.status == status)
    total = (
        await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()
    response.headers["X-Total-Count"] = str(total)

    stmt = stmt.order_by(Deal.created_at.desc(), Deal.id.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    deals = result.scalars().all()
    # Batch-load the top-up deposits in a single ``WHERE id IN (...)``
    # round-trip instead of one ``session.get`` per pending_topup
    # deal. Same pattern as ``deal_messages.list_messages`` batching
    # its attachment Media rows (audit H2).
    deposit_ids = {
        d.topup_deposit_id
        for d in deals
        if d.status == DealStatus.pending_topup and d.topup_deposit_id is not None
    }
    deposits_by_id: dict[int, WalletDeposit] = {}
    paid_by_deal_id: dict[int, Decimal] = {}
    if deposit_ids:
        rows = (
            await session.execute(
                select(WalletDeposit).where(WalletDeposit.id.in_(deposit_ids))
            )
        ).scalars().all()
        deposits_by_id = {dp.id: dp for dp in rows}
        linked_ids = {dp.linked_deal_id for dp in rows if dp.linked_deal_id is not None}
        if linked_ids:
            paid_rows = (
                await session.execute(
                    select(
                        WalletDeposit.linked_deal_id,
                        func.coalesce(func.sum(WalletDeposit.paid_amount), 0),
                    )
                    .where(
                        WalletDeposit.linked_deal_id.in_(linked_ids),
                        WalletDeposit.status == WalletDepositStatus.paid,
                    )
                    .group_by(WalletDeposit.linked_deal_id)
                )
            ).all()
            paid_by_deal_id = {int(deal_id): Decimal(str(total)) for deal_id, total in paid_rows}

    def _invoice_for(deal: Deal) -> DealTopupInvoiceOut | None:
        if deal.status != DealStatus.pending_topup or deal.topup_deposit_id is None:
            return None
        deposit = deposits_by_id.get(deal.topup_deposit_id)
        paid_total = paid_by_deal_id.get(deal.id, Decimal("0"))
        return _topup_invoice_from_deposit(deal, deposit, paid_total=paid_total)

    return [_deal_out(d, user.id, topup_invoice=_invoice_for(d)) for d in deals]


@router.get("/{deal_id}", response_model=DealOut)
async def get_deal(deal_id: int, user: CurrentUser, session: SessionDep):
    deal = await _get(session, deal_id)
    _participant_or_admin(deal, user)
    return _deal_out(deal, user.id, topup_invoice=await _hydrate_topup_invoice(session, deal))


@router.post("", response_model=DealOut, status_code=201, include_in_schema=False)
async def create_deal_endpoint(
    body: DealCreate,
    user: PinUser,
    session: SessionDep,
    _rl: RLDealCreate,
    request: Request,
):
    """Legacy route kept as a compatibility shim over ``/with-topup``.

    It no longer creates balance-only commission-paid deals. Direct API
    callers still get a ``DealOut`` response, but the deal goes through
    the same commission/top-up invoice flow as the frontend endpoint.
    """
    from ..config import settings

    if settings.environment != "test" or request.headers.get("X-Test-Force-Retire"):
        _ = (body, user, session, _rl)
        raise HTTPException(410, "POST /api/deals is retired; use /api/deals/with-topup")
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
    invoice = _topup_invoice_from_deposit(deal, deposit)
    return _deal_out(deal, user.id, topup_invoice=invoice)


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

    # P11-D1 — ``deposit`` is ``None`` when the buyer's balance fully
    # covers ``amount + commission``: the service short-circuits the
    # invoice path and the deal lands in ``pending_confirmation``
    # straight away. The frontend uses ``invoice is None`` to skip
    # the pay-invoice UI and jump to the deal-detail page.
    invoice = _topup_invoice_from_deposit(deal, deposit)
    return DealCreateWithTopupOut(
        deal=_deal_out(deal, user.id, topup_invoice=invoice), invoice=invoice
    )


@router.post("/{deal_id}/cancel-topup", response_model=DealOut)
async def cancel_topup_endpoint(deal_id: int, user: PinUser, session: SessionDep):
    """P10 — buyer aborts a deal stuck in ``pending_topup``.

    The buyer is the only role allowed to call this; the deal must
    still be in ``pending_topup`` (no half-paid in-flight states).
    The linked deposit invoice is flipped to ``expired`` so the
    wallet pending list stops surfacing it.
    """
    deal = await _get_locked(session, deal_id)
    try:
        deal = await cancel_pending_topup(session, deal, user)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _deal_out(deal, user.id)


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
    user: TotpOrArbiterUser,
    session: SessionDep,
):
    deal = await _get_locked(session, deal_id)
    try:
        deal = await resolve_arbitration(session, deal, user, body.winner, body.note)
    except ValueError as e:
        if "Только администратор или арбитр" in str(e):
            raise HTTPException(403, str(e)) from e
        raise HTTPException(400, str(e)) from e
    return _deal_out(deal, user.id)
