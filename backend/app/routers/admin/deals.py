"""Admin deal management — ``/api/admin/deals``.

Implements the deal-related subset of the admin-panel spec:

* List with filters (status, currency, sum range, date range, has-arbitration,
  has-cancel-request) and pagination.
* Detail view with a reconstructed event timeline, balance snapshot for
  both parties, and the full chat transcript.
* Privileged actions:

  - ``force-release`` — pay out to seller (release locked funds, keep
    commission).
  - ``force-refund``  — refund buyer (return locked + commission share).
  - ``split``         — split the locked pot X% buyer / (100-X)% seller;
    commission is always retained by the platform.
  - ``force-arbitration`` — move a deal into arbitration manually.
  - ``assign-arbiter`` — assign / clear the arbiter handling the dispute.
  - ``delete``        — instant deletion at *any* stage with refund of
    whatever is still locked, plus DMs to both parties.

Every mutation writes a row to ``admin_audit_log`` in the same SQL
transaction as the change, so a partial failure rolls back both. Side
effects (DMs, in-app notifications) run after commit.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ... import notifier
from ...admin_audit import log_admin_action
from ...auth_2fa import TotpUser
from ...deps import AdminUser, SessionDep
from ...models import (
    Currency,
    Deal,
    DealMessage,
    DealStatus,
    NotificationType,
    PayCommission,
    User,
)
from ...rate_limit import rate_limit
from ...schemas import (
    AdminBalanceSnapshot,
    AdminDealActionResult,
    AdminDealAssignArbiterIn,
    AdminDealDetailOut,
    AdminDealEventItem,
    AdminDealForceOut,
    AdminDealListItem,
    AdminDealListOut,
    AdminDealSplitIn,
    DealMessageOut,
)
from ...services_wallet import get_or_create_balance

router = APIRouter(
    prefix="/api/admin/deals",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin", limit=600, window=60))],
)


# --------------------------------------------------------------------- helpers


def _q(value: Decimal | float | int, decimals: int) -> Decimal:
    quant = Decimal(10) ** -decimals
    return Decimal(str(value)).quantize(quant)


async def _get_deal_or_404(session: AsyncSession, deal_id: int, *, lock: bool = False) -> Deal:
    if lock:
        deal = (
            await session.execute(select(Deal).where(Deal.id == deal_id).with_for_update())
        ).scalar_one_or_none()
    else:
        deal = await session.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "Сделка не найдена")
    return deal


async def _balance_snapshot(
    session: AsyncSession, user: User, currency: Currency | None
) -> AdminBalanceSnapshot:
    if currency is None:
        return AdminBalanceSnapshot(
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            currency_code=None,
            amount=float(user.balance),
            locked=0.0,
            total=float(user.balance),
        )
    balance = await get_or_create_balance(session, user.id, currency.id)
    amount = float(balance.amount)
    locked = float(balance.locked)
    return AdminBalanceSnapshot(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        currency_code=currency.code,
        amount=amount,
        locked=locked,
        total=amount + locked,
    )


def _event(
    at: datetime | None, kind: str, actor: str | None, description: str
) -> AdminDealEventItem | None:
    if at is None:
        return None
    return AdminDealEventItem(at=at, kind=kind, actor=actor, description=description)


def _actor_label(deal: Deal, user_id: int | None) -> str | None:
    if user_id is None:
        return None
    if user_id == deal.buyer_id:
        return "buyer"
    if user_id == deal.seller_id:
        return "seller"
    return "staff"


def _build_events(deal: Deal) -> list[AdminDealEventItem]:
    """Reconstruct the deal timeline from the columns on the row.

    We don't have a dedicated ``deal_events`` table — every notable
    state transition stamps its own ``*_at`` column. The timeline shows
    each non-null stamp as a separate row, sorted oldest-first.
    """
    items: list[AdminDealEventItem] = []
    items.append(
        AdminDealEventItem(
            at=deal.created_at,
            kind="created",
            actor="buyer",
            description="Сделка создана",
        )
    )
    e = _event(deal.in_progress_at, "in_progress", "seller", "Продавец принял сделку")
    if e:
        items.append(e)
    if deal.cancellation_requested_at is not None:
        items.append(
            AdminDealEventItem(
                at=deal.cancellation_requested_at,
                kind="cancel_request",
                actor=_actor_label(deal, deal.cancellation_initiator_id),
                description=deal.cancellation_reason or "Запрошена отмена",
            )
        )
    if deal.arbitration_resolved_at is None and deal.status == DealStatus.arbitration:
        items.append(
            AdminDealEventItem(
                at=deal.cancellation_requested_at or deal.in_progress_at or deal.created_at,
                kind="arbitration_started",
                actor=_actor_label(deal, deal.arbitration_initiator_id),
                description=deal.arbitration_reason or "Спор открыт",
            )
        )
    if deal.arbitration_resolved_at is not None:
        items.append(
            AdminDealEventItem(
                at=deal.arbitration_resolved_at,
                kind="arbitration_resolved",
                actor="arbiter",
                description=f"Решение: {deal.arbitration_resolution or '—'}",
            )
        )
    if deal.completed_at is not None:
        items.append(
            AdminDealEventItem(
                at=deal.completed_at,
                kind="completed",
                actor=None,
                description=f"Финальный статус: {deal.status.value}",
            )
        )
    items.sort(key=lambda x: x.at)
    return items


async def _serialize_message(session: AsyncSession, msg: DealMessage) -> DealMessageOut:
    # Lazy import to avoid a circular dependency with deal_messages router.
    from ..deal_messages import _serialize  # type: ignore[attr-defined]

    return await _serialize(session, msg)


async def _list_messages(session: AsyncSession, deal_id: int) -> list[DealMessageOut]:
    rows = (
        (
            await session.execute(
                select(DealMessage)
                .where(DealMessage.deal_id == deal_id)
                .order_by(DealMessage.created_at.asc(), DealMessage.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return [await _serialize_message(session, m) for m in rows]


async def _to_detail(session: AsyncSession, deal: Deal) -> AdminDealDetailOut:
    currency = await session.get(Currency, deal.currency_id) if deal.currency_id else None
    buyer = await session.get(User, deal.buyer_id)
    seller = await session.get(User, deal.seller_id)
    assert buyer is not None and seller is not None
    buyer_snap = await _balance_snapshot(session, buyer, currency)
    seller_snap = await _balance_snapshot(session, seller, currency)
    arbiter_username: str | None = None
    if deal.arbitration_resolved_by is not None:
        arbiter = await session.get(User, deal.arbitration_resolved_by)
        arbiter_username = arbiter.username if arbiter else None
    return AdminDealDetailOut(
        id=deal.id,
        status=deal.status.value,
        description=deal.description,
        sum=float(deal.sum),
        currency_code=currency.code if currency else None,
        amount=float(deal.amount) if deal.amount is not None else None,
        commission_amount=(
            float(deal.commission_amount) if deal.commission_amount is not None else None
        ),
        pay_commission=deal.pay_commission.value,
        buyer=buyer_snap,
        seller=seller_snap,
        created_at=deal.created_at,
        in_progress_at=deal.in_progress_at,
        completed_at=deal.completed_at,
        cancellation_initiator=_actor_label(deal, deal.cancellation_initiator_id),
        cancellation_reason=deal.cancellation_reason,
        cancellation_requested_at=deal.cancellation_requested_at,
        arbitration_initiator=_actor_label(deal, deal.arbitration_initiator_id),
        arbitration_reason=deal.arbitration_reason,
        arbitration_resolved_by_id=deal.arbitration_resolved_by,
        arbitration_resolved_by_username=arbiter_username,
        arbitration_resolution=deal.arbitration_resolution,
        arbitration_resolved_at=deal.arbitration_resolved_at,
        confirm_buyer=deal.confirm_buyer,
        confirm_seller=deal.confirm_seller,
        events=_build_events(deal),
        messages=await _list_messages(session, deal.id),
    )


def _to_list_item(deal: Deal) -> AdminDealListItem:
    return AdminDealListItem(
        id=deal.id,
        status=deal.status.value,
        sum=float(deal.sum),
        currency_code=deal.currency.code if deal.currency else None,
        amount=float(deal.amount) if deal.amount is not None else None,
        commission_amount=(
            float(deal.commission_amount) if deal.commission_amount is not None else None
        ),
        buyer_id=deal.buyer_id,
        buyer_username=deal.buyer.username if deal.buyer else None,
        seller_id=deal.seller_id,
        seller_username=deal.seller.username if deal.seller else None,
        pay_commission=deal.pay_commission.value,
        created_at=deal.created_at,
        in_progress_at=deal.in_progress_at,
        completed_at=deal.completed_at,
        has_arbitration=deal.status == DealStatus.arbitration,
        has_cancel_request=deal.status == DealStatus.pending_cancellation,
    )


async def _audit(
    *,
    session: AsyncSession,
    request: Request,
    admin: User,
    deal: Deal,
    action: str,
    reason: str | None,
    payload: dict | None,
) -> None:
    await log_admin_action(
        session,
        actor=admin,
        action=action,
        target_type="deal",
        target_id=deal.id,
        reason=reason,
        payload=payload,
        request=request,
    )


async def _notify_party(
    session: AsyncSession, user_id: int, title: str, body: str, deal_id: int
) -> None:
    try:
        await notifier.push(
            session,
            user_id,
            NotificationType.deals,
            title,
            body,
            {"deal_id": deal_id},
        )
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------- listing


_STATUS_CHOICES = (
    "any",
    "cancelled",
    "pending_confirmation",
    "pending_payment",
    "in_progress",
    "completed",
    "arbitration",
    "resolved_for_buyer",
    "resolved_for_seller",
    "pending_cancellation",
    "cancelled_for_inactivity",
)


@router.get("", response_model=AdminDealListOut)
async def list_deals(
    _admin: AdminUser,
    session: SessionDep,
    status: Annotated[str, Query()] = "any",
    currency: Annotated[str | None, Query()] = None,
    min_sum: Annotated[float | None, Query()] = None,
    max_sum: Annotated[float | None, Query()] = None,
    has_arbitration: Annotated[bool | None, Query()] = None,
    has_cancel_request: Annotated[bool | None, Query()] = None,
    buyer_id: Annotated[int | None, Query()] = None,
    seller_id: Annotated[int | None, Query()] = None,
    created_from: Annotated[datetime | None, Query()] = None,
    created_to: Annotated[datetime | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminDealListOut:
    stmt = select(Deal)
    count_stmt = select(func.count()).select_from(Deal)

    filters = []
    if status != "any":
        if status not in _STATUS_CHOICES:
            raise HTTPException(400, "Неверный статус")
        try:
            filters.append(Deal.status == DealStatus(status))
        except ValueError:
            raise HTTPException(400, "Неверный статус")  # noqa: B904
    if currency:
        cur = (
            await session.execute(select(Currency).where(Currency.code == currency.upper()))
        ).scalar_one_or_none()
        if cur is None:
            raise HTTPException(404, f"Валюта {currency} не поддерживается")
        filters.append(Deal.currency_id == cur.id)
    if min_sum is not None:
        filters.append(Deal.sum >= min_sum)
    if max_sum is not None:
        filters.append(Deal.sum <= max_sum)
    if has_arbitration is True:
        filters.append(Deal.status == DealStatus.arbitration)
    if has_cancel_request is True:
        filters.append(Deal.status == DealStatus.pending_cancellation)
    if buyer_id is not None:
        filters.append(Deal.buyer_id == buyer_id)
    if seller_id is not None:
        filters.append(Deal.seller_id == seller_id)
    if created_from is not None:
        filters.append(Deal.created_at >= created_from)
    if created_to is not None:
        filters.append(Deal.created_at <= created_to)

    if filters:
        where_clause = and_(*filters)
        stmt = stmt.where(where_clause)
        count_stmt = count_stmt.where(where_clause)

    stmt = stmt.order_by(Deal.created_at.desc()).offset((page - 1) * page_size).limit(page_size)

    rows = (await session.execute(stmt)).scalars().all()
    total = int((await session.execute(count_stmt)).scalar_one() or 0)

    return AdminDealListOut(
        items=[_to_list_item(d) for d in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{deal_id}", response_model=AdminDealDetailOut)
async def get_deal(deal_id: int, _admin: AdminUser, session: SessionDep) -> AdminDealDetailOut:
    deal = await _get_deal_or_404(session, deal_id)
    return await _to_detail(session, deal)


# --------------------------------------------------------------------- actions


def _is_terminal(status: DealStatus) -> bool:
    return status in (
        DealStatus.cancelled,
        DealStatus.completed,
        DealStatus.resolved_for_buyer,
        DealStatus.resolved_for_seller,
        DealStatus.cancelled_for_inactivity,
    )


async def _release_locked_to_seller(
    session: AsyncSession, deal: Deal, currency: Currency
) -> tuple[Decimal, Decimal]:
    """Move locked funds from buyer to seller, retaining commission.

    Returns ``(locked_pot, payout)`` for the audit record.
    """
    decimals = currency.decimals
    amt = _q(Decimal(str(deal.amount or 0)), decimals)
    commission = _q(Decimal(str(deal.commission_amount or 0)), decimals)
    if deal.pay_commission == PayCommission.buyer:
        locked = amt + commission
        payout = amt
    else:
        locked = amt
        payout = amt - commission

    buyer_balance = await get_or_create_balance(session, deal.buyer_id, currency.id)
    buyer_balance.locked = float(max(Decimal(0), Decimal(str(buyer_balance.locked)) - locked))
    seller_balance = await get_or_create_balance(session, deal.seller_id, currency.id)
    seller_balance.amount = float(Decimal(str(seller_balance.amount)) + payout)
    return locked, payout


async def _refund_locked_to_buyer(
    session: AsyncSession, deal: Deal, currency: Currency
) -> tuple[Decimal, Decimal]:
    """Unlock locked funds and credit *only the principal* back to the buyer.

    Per spec, commission is charged on every deal regardless of outcome,
    so a buyer-paid commission stays in the platform pool on refund.
    Returns ``(locked_pot, refunded_principal)``.
    """
    decimals = currency.decimals
    amt = _q(Decimal(str(deal.amount or 0)), decimals)
    commission = _q(Decimal(str(deal.commission_amount or 0)), decimals)
    if deal.pay_commission == PayCommission.buyer:
        locked = amt + commission
        refunded = amt
    else:
        locked = amt
        refunded = amt

    buyer_balance = await get_or_create_balance(session, deal.buyer_id, currency.id)
    buyer_balance.locked = float(max(Decimal(0), Decimal(str(buyer_balance.locked)) - locked))
    buyer_balance.amount = float(Decimal(str(buyer_balance.amount)) + refunded)
    return locked, refunded


async def _split_locked(
    session: AsyncSession,
    deal: Deal,
    currency: Currency,
    buyer_percent: float,
) -> tuple[Decimal, Decimal, Decimal]:
    """Split the principal between buyer and seller; commission is kept.

    Returns ``(locked_pot, buyer_share, seller_share)``.
    """
    decimals = currency.decimals
    amt = _q(Decimal(str(deal.amount or 0)), decimals)
    commission = _q(Decimal(str(deal.commission_amount or 0)), decimals)
    locked = amt + commission if deal.pay_commission == PayCommission.buyer else amt
    # ``amt`` already excludes commission; split principal between
    # parties. The buyer-paid commission portion stays on the platform.
    buyer_share = _q(amt * Decimal(str(buyer_percent)) / Decimal(100), decimals)
    seller_share = amt - buyer_share

    buyer_balance = await get_or_create_balance(session, deal.buyer_id, currency.id)
    buyer_balance.locked = float(max(Decimal(0), Decimal(str(buyer_balance.locked)) - locked))
    buyer_balance.amount = float(Decimal(str(buyer_balance.amount)) + buyer_share)
    seller_balance = await get_or_create_balance(session, deal.seller_id, currency.id)
    seller_balance.amount = float(Decimal(str(seller_balance.amount)) + seller_share)
    return locked, buyer_share, seller_share


def _is_active_for_money_movement(status: DealStatus) -> bool:
    """A deal still has locked money iff it hasn't terminated yet."""
    return status in (
        DealStatus.pending_confirmation,
        DealStatus.pending_payment,
        DealStatus.in_progress,
        DealStatus.pending_cancellation,
        DealStatus.arbitration,
    )


@router.post("/{deal_id}/force-release", response_model=AdminDealActionResult)
async def force_release(
    deal_id: int,
    body: AdminDealForceOut,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminDealActionResult:
    deal = await _get_deal_or_404(session, deal_id, lock=True)
    if _is_terminal(deal.status):
        raise HTTPException(400, "Сделка уже завершена")
    if deal.currency_id is None or deal.amount is None:
        raise HTTPException(400, "У сделки не задана валюта")
    currency = await session.get(Currency, deal.currency_id)
    assert currency is not None

    before_status = deal.status.value
    locked, payout = await _release_locked_to_seller(session, deal, currency)
    deal.status = DealStatus.resolved_for_seller
    deal.completed_at = datetime.utcnow()
    deal.arbitration_resolved_by = admin.id
    deal.arbitration_resolution = "seller"
    if deal.arbitration_resolved_at is None:
        deal.arbitration_resolved_at = datetime.utcnow()

    await _audit(
        session=session,
        request=request,
        admin=admin,
        deal=deal,
        action="deal.force_release",
        reason=body.reason,
        payload={
            "before_status": before_status,
            "after_status": deal.status.value,
            "currency": currency.code,
            "locked": float(locked),
            "payout": float(payout),
        },
    )
    await session.commit()
    await session.refresh(deal)
    await _notify_party(
        session,
        deal.seller_id,
        "Сделка завершена администратором",
        f"Сделка #{deal.id} завершена в вашу пользу. Сумма {payout} {currency.code} зачислена на баланс.",
        deal.id,
    )
    await _notify_party(
        session,
        deal.buyer_id,
        "Сделка завершена администратором",
        f"Сделка #{deal.id} завершена в пользу продавца.",
        deal.id,
    )
    return AdminDealActionResult(deal=await _to_detail(session, deal))


@router.post("/{deal_id}/force-refund", response_model=AdminDealActionResult)
async def force_refund(
    deal_id: int,
    body: AdminDealForceOut,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminDealActionResult:
    deal = await _get_deal_or_404(session, deal_id, lock=True)
    if _is_terminal(deal.status):
        raise HTTPException(400, "Сделка уже завершена")
    if deal.currency_id is None or deal.amount is None:
        raise HTTPException(400, "У сделки не задана валюта")
    currency = await session.get(Currency, deal.currency_id)
    assert currency is not None

    before_status = deal.status.value
    locked, refunded = await _refund_locked_to_buyer(session, deal, currency)
    deal.status = DealStatus.resolved_for_buyer
    deal.completed_at = datetime.utcnow()
    deal.arbitration_resolved_by = admin.id
    deal.arbitration_resolution = "buyer"
    if deal.arbitration_resolved_at is None:
        deal.arbitration_resolved_at = datetime.utcnow()

    await _audit(
        session=session,
        request=request,
        admin=admin,
        deal=deal,
        action="deal.force_refund",
        reason=body.reason,
        payload={
            "before_status": before_status,
            "after_status": deal.status.value,
            "currency": currency.code,
            "locked": float(locked),
            "refunded": float(refunded),
        },
    )
    await session.commit()
    await session.refresh(deal)
    await _notify_party(
        session,
        deal.buyer_id,
        "Сделка возвращена администратором",
        f"Сделка #{deal.id} закрыта в вашу пользу, возвращено {refunded} {currency.code} (комиссия удержана).",
        deal.id,
    )
    await _notify_party(
        session,
        deal.seller_id,
        "Сделка возвращена администратором",
        f"Сделка #{deal.id} закрыта в пользу покупателя.",
        deal.id,
    )
    return AdminDealActionResult(deal=await _to_detail(session, deal))


@router.post("/{deal_id}/split", response_model=AdminDealActionResult)
async def split_deal(
    deal_id: int,
    body: AdminDealSplitIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminDealActionResult:
    deal = await _get_deal_or_404(session, deal_id, lock=True)
    if _is_terminal(deal.status):
        raise HTTPException(400, "Сделка уже завершена")
    if deal.currency_id is None or deal.amount is None:
        raise HTTPException(400, "У сделки не задана валюта")
    currency = await session.get(Currency, deal.currency_id)
    assert currency is not None

    before_status = deal.status.value
    locked, buyer_share, seller_share = await _split_locked(
        session, deal, currency, body.buyer_percent
    )
    deal.status = (
        DealStatus.resolved_for_buyer
        if body.buyer_percent >= 50
        else DealStatus.resolved_for_seller
    )
    deal.completed_at = datetime.utcnow()
    deal.arbitration_resolved_by = admin.id
    deal.arbitration_resolution = "buyer" if body.buyer_percent >= 50 else "seller"
    if deal.arbitration_resolved_at is None:
        deal.arbitration_resolved_at = datetime.utcnow()

    await _audit(
        session=session,
        request=request,
        admin=admin,
        deal=deal,
        action="deal.split",
        reason=body.reason,
        payload={
            "before_status": before_status,
            "after_status": deal.status.value,
            "currency": currency.code,
            "buyer_percent": body.buyer_percent,
            "buyer_share": float(buyer_share),
            "seller_share": float(seller_share),
            "locked": float(locked),
        },
    )
    await session.commit()
    await session.refresh(deal)
    await _notify_party(
        session,
        deal.buyer_id,
        "Сделка разделена администратором",
        f"По сделке #{deal.id} вам возвращено {buyer_share} {currency.code}.",
        deal.id,
    )
    await _notify_party(
        session,
        deal.seller_id,
        "Сделка разделена администратором",
        f"По сделке #{deal.id} вам начислено {seller_share} {currency.code}.",
        deal.id,
    )
    return AdminDealActionResult(deal=await _to_detail(session, deal))


@router.post("/{deal_id}/force-arbitration", response_model=AdminDealActionResult)
async def force_arbitration(
    deal_id: int,
    body: AdminDealForceOut,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminDealActionResult:
    deal = await _get_deal_or_404(session, deal_id, lock=True)
    if _is_terminal(deal.status):
        raise HTTPException(400, "Сделка уже завершена")
    if deal.status == DealStatus.arbitration:
        # Idempotent — return current state without writing a new audit row.
        return AdminDealActionResult(deal=await _to_detail(session, deal))

    before = deal.status.value
    deal.status = DealStatus.arbitration
    deal.arbitration_initiator_id = admin.id
    deal.arbitration_reason = body.reason or "Открыто администратором"

    await _audit(
        session=session,
        request=request,
        admin=admin,
        deal=deal,
        action="deal.force_arbitration",
        reason=body.reason,
        payload={"before_status": before, "after_status": deal.status.value},
    )
    await session.commit()
    await session.refresh(deal)
    for recipient_id in (deal.buyer_id, deal.seller_id):
        await _notify_party(
            session,
            recipient_id,
            "Открыт арбитраж",
            f"По сделке #{deal.id} открыт арбитраж администратором.",
            deal.id,
        )
    return AdminDealActionResult(deal=await _to_detail(session, deal))


@router.post("/{deal_id}/assign-arbiter", response_model=AdminDealActionResult)
async def assign_arbiter(
    deal_id: int,
    body: AdminDealAssignArbiterIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminDealActionResult:
    deal = await _get_deal_or_404(session, deal_id, lock=True)
    if deal.status != DealStatus.arbitration:
        raise HTTPException(400, "Назначить арбитра можно только для сделки в арбитраже")

    if body.arbiter_id is not None:
        arbiter = await session.get(User, body.arbiter_id)
        if arbiter is None:
            raise HTTPException(404, "Пользователь не найден")
        if not (arbiter.is_arbiter or arbiter.is_admin):
            raise HTTPException(400, "Назначаемый пользователь не имеет роли арбитра")

    before = deal.arbitration_resolved_by
    if before == body.arbiter_id:
        return AdminDealActionResult(deal=await _to_detail(session, deal))

    deal.arbitration_resolved_by = body.arbiter_id

    await _audit(
        session=session,
        request=request,
        admin=admin,
        deal=deal,
        action="deal.assign_arbiter",
        reason=None,
        payload={"before": before, "after": body.arbiter_id},
    )
    await session.commit()
    await session.refresh(deal)
    if body.arbiter_id is not None:
        await _notify_party(
            session,
            body.arbiter_id,
            "Назначен арбитр",
            f"Вам назначена сделка #{deal.id} для арбитража.",
            deal.id,
        )
    return AdminDealActionResult(deal=await _to_detail(session, deal))


@router.post("/{deal_id}/delete", status_code=200)
async def delete_deal(
    deal_id: int,
    body: AdminDealForceOut,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> dict:
    """Instant delete at any stage.

    If the deal still has locked funds (non-terminal status), the funds
    are atomically refunded to the buyer in the same transaction as the
    deletion. ``admin_audit_log`` keeps a permanent payload snapshot of
    the deleted deal so the action remains visible after the row is
    gone.
    """
    deal = await _get_deal_or_404(session, deal_id, lock=True)
    currency = await session.get(Currency, deal.currency_id) if deal.currency_id else None

    snapshot = {
        "id": deal.id,
        "status": deal.status.value,
        "buyer_id": deal.buyer_id,
        "seller_id": deal.seller_id,
        "sum": float(deal.sum),
        "currency": currency.code if currency else None,
        "amount": float(deal.amount) if deal.amount is not None else None,
        "commission_amount": (
            float(deal.commission_amount) if deal.commission_amount is not None else None
        ),
        "pay_commission": deal.pay_commission.value,
        "created_at": deal.created_at.isoformat() if deal.created_at else None,
    }
    refunded: Decimal | None = None
    if currency is not None and _is_active_for_money_movement(deal.status):
        # Delete is the admin nuclear option — returns the full locked
        # pot (including any commission share) because the deal row
        # disappears from the treasury accrual query too. This is the
        # one path that does NOT retain commission.
        decimals = currency.decimals
        amt = _q(Decimal(str(deal.amount or 0)), decimals)
        commission = _q(Decimal(str(deal.commission_amount or 0)), decimals)
        if deal.pay_commission == PayCommission.buyer:
            locked_pot = amt + commission
        else:
            locked_pot = amt
        buyer_balance = await get_or_create_balance(session, deal.buyer_id, currency.id)
        buyer_balance.locked = float(
            max(Decimal(0), Decimal(str(buyer_balance.locked)) - locked_pot)
        )
        buyer_balance.amount = float(Decimal(str(buyer_balance.amount)) + locked_pot)
        refunded = locked_pot
        snapshot["refunded"] = float(refunded)

    # Clean up dependent rows: messages reference the deal via FK.
    await session.execute(DealMessage.__table__.delete().where(DealMessage.deal_id == deal.id))

    buyer_id = deal.buyer_id
    seller_id = deal.seller_id
    deal_id_local = deal.id

    await _audit(
        session=session,
        request=request,
        admin=admin,
        deal=deal,
        action="deal.delete",
        reason=body.reason,
        payload=snapshot,
    )
    await session.delete(deal)
    await session.commit()

    for recipient_id, role in ((buyer_id, "buyer"), (seller_id, "seller")):
        body_text = f"Сделка #{deal_id_local} удалена администратором." + (
            f" Вам возвращено {refunded} {currency.code}."
            if (refunded is not None and currency is not None and role == "buyer")
            else ""
        )
        await _notify_party(session, recipient_id, "Сделка удалена", body_text, deal_id_local)

    return {
        "deleted": True,
        "deal_id": deal_id_local,
        "refunded": float(refunded) if refunded is not None else None,
    }
