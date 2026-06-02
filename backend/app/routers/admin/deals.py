"""Admin deal management — ``/api/admin/deals``.

Implements the deal-related subset of the admin-panel spec:

* List with filters (status, currency, amount range, date range, has-arbitration,
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

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ... import notifier
from ...admin_audit import log_admin_action
from ...admin_guard import TotpUser
from ...config import settings
from ...deps import AdminUser, SessionDep
from ...models import (
    AdminApprovalRequest,
    Currency,
    CurrencyUsdRate,
    Deal,
    DealMessage,
    DealStatus,
    Media,
    Notification,
    NotificationType,
    User,
    UserBalance,
)
from ...money import quantize_money
from ...rate_limit import rate_limit
from ...schemas import (
    AdminApprovalOut,
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
from ...services_ledger import record_balance_ledger
from ...services_wallet import get_or_create_balance, lock_user_balance
from ...time_utils import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/deals",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin:deals", limit=600, window=60))],
)


# --------------------------------------------------------------------- helpers


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
    # M-20: keep balance arithmetic in ``Decimal`` end-to-end so the
    # ``total`` we hand to the schema is computed exactly. The schema
    # still declares ``float`` (legacy wire format); the full Decimal
    # wire format change is tracked under M-3 / M-9.
    #
    # H-1: post-migration ``deal.currency_id`` is non-null on every
    # row (legacy USD-only deals were backfilled to USDT by the H-1
    # migration). The ``currency is None`` branch is kept as a
    # defensive empty snapshot for the (theoretical) case of a deal
    # whose ``currency_id`` references a row that has since been
    # purged from ``currencies``; it no longer carries the dead
    # ``user.balance`` USD column.
    if currency is None:
        zero = Decimal(0)
        return AdminBalanceSnapshot(
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            currency_code=None,
            amount=zero,
            locked=zero,
            total=zero,
        )
    balance = await get_or_create_balance(session, user.id, currency.id)
    # H-2: quantise to ``currency.decimals`` with ``ROUND_HALF_EVEN``
    # (see ``backend/app/money.py``) so the admin deal detail panel
    # never renders trailing satoshi noise the row itself doesn't
    # carry.
    amount = quantize_money(balance.amount, currency.decimals)
    locked = quantize_money(balance.locked, currency.decimals)
    return AdminBalanceSnapshot(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        currency_code=currency.code,
        amount=amount,
        locked=locked,
        total=quantize_money(amount + locked, currency.decimals),
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


async def _list_messages(session: AsyncSession, deal_id: int) -> list[DealMessageOut]:
    """Latest admin chat transcript page — batched media load.

    Audit M-37 — the admin deal detail endpoint embeds a small chat
    preview, not the full transcript. The full history is paged by the
    shared ``GET /api/deals/{id}/messages`` cursor endpoint that the
    admin UI also uses for "load older".
    """
    # Lazy import to avoid a circular dependency with deal_messages router.
    from ..deal_messages import _DEFAULT_MESSAGE_PAGE, _parse_attachment_ids, _serialize_one

    page = (
        (
            await session.execute(
                select(DealMessage)
                .where(DealMessage.deal_id == deal_id)
                .options(selectinload(DealMessage.sender))
                .order_by(DealMessage.id.desc())
                .limit(_DEFAULT_MESSAGE_PAGE)
            )
        )
        .scalars()
        .all()
    )
    rows = list(reversed(page))
    # Audit M-4 — collect every attachment id across the page in one
    # pass, then issue a single ``WHERE id IN (...)`` SELECT. ``set``
    # collapses duplicate ids into one DB-side fetch.
    all_media_ids: set[int] = set()
    for msg in rows:
        all_media_ids.update(_parse_attachment_ids(msg.attachments_json))
    media_by_id: dict[int, Media] = {}
    if all_media_ids:
        media_rows = (
            (await session.execute(select(Media).where(Media.id.in_(all_media_ids))))
            .scalars()
            .all()
        )
        media_by_id = {m.id: m for m in media_rows}
    return [_serialize_one(m, media_by_id) for m in rows]


async def _to_detail(session: AsyncSession, deal: Deal) -> AdminDealDetailOut:
    currency = await session.get(Currency, deal.currency_id) if deal.currency_id else None
    buyer = await session.get(User, deal.buyer_id)
    seller = await session.get(User, deal.seller_id)
    # M-1: ``assert`` is stripped under ``python -O``; raise explicitly
    # so a corrupt FK never silently dereferences ``None`` downstream.
    if buyer is None or seller is None:
        raise HTTPException(500, "Внутренняя ошибка: участник сделки не найден")
    buyer_snap = await _balance_snapshot(session, buyer, currency)
    seller_snap = await _balance_snapshot(session, seller, currency)
    arbiter_username: str | None = None
    if deal.arbitration_resolved_by is not None:
        arbiter = await session.get(User, deal.arbitration_resolved_by)
        arbiter_username = arbiter.username if arbiter else None
    # H-2: quantise the deal money projection on output so the admin
    # detail screen never shows more fractional digits than the deal's
    # own currency uses. ``commission_amount`` can legitimately be
    # null on a brand-new row, so preserve the ``None`` instead of
    # quantising a sentinel.
    decimals = currency.decimals if currency is not None else 8
    amount_q = quantize_money(deal.amount, decimals)
    commission_q = (
        quantize_money(deal.commission_amount, decimals)
        if deal.commission_amount is not None
        else None
    )
    approval_rows = (
        (
            await session.execute(
                select(AdminApprovalRequest)
                .where(
                    AdminApprovalRequest.target_type == "deal",
                    AdminApprovalRequest.target_id == deal.id,
                    AdminApprovalRequest.status.in_(("pending", "approved")),
                )
                .options(selectinload(AdminApprovalRequest.currency))
                .order_by(AdminApprovalRequest.created_at.desc(), AdminApprovalRequest.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return AdminDealDetailOut(
        id=deal.id,
        status=deal.status.value,
        description=deal.description,
        currency_code=currency.code if currency else None,
        amount=amount_q,
        commission_amount=commission_q,
        commission_paid=bool(deal.commission_paid),
        topup_deposit_id=deal.topup_deposit_id,
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
        pending_approvals=[_approval_out(row) for row in approval_rows],
    )


def _to_list_item(deal: Deal) -> AdminDealListItem:
    # H-2: quantise on output — see the matching note in ``_to_detail``.
    decimals = deal.currency.decimals if deal.currency is not None else 8
    amount_q = quantize_money(deal.amount, decimals)
    commission_q = (
        quantize_money(deal.commission_amount, decimals)
        if deal.commission_amount is not None
        else None
    )
    return AdminDealListItem(
        id=deal.id,
        status=deal.status.value,
        currency_code=deal.currency.code if deal.currency else None,
        amount=amount_q,
        commission_amount=commission_q,
        buyer_id=deal.buyer_id,
        buyer_username=deal.buyer.username if deal.buyer else None,
        seller_id=deal.seller_id,
        seller_username=deal.seller.username if deal.seller else None,
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


def _approval_out(row: AdminApprovalRequest) -> AdminApprovalOut:
    currency_code = row.currency.code if row.currency is not None else None
    return AdminApprovalOut(
        id=row.id,
        action=row.action,
        target_type=row.target_type,
        target_id=row.target_id,
        status=row.status,
        requested_by_id=row.requested_by_id,
        approved_by_id=row.approved_by_id,
        executed_by_id=row.executed_by_id,
        currency_code=currency_code,
        amount=Decimal(str(row.amount)) if row.amount is not None else None,
        amount_usd_estimate=(
            Decimal(str(row.amount_usd_estimate)) if row.amount_usd_estimate is not None else None
        ),
        reason=row.reason,
        payload=row.payload,
        created_at=row.created_at,
        approved_at=row.approved_at,
        executed_at=row.executed_at,
        rejected_at=row.rejected_at,
    )


async def _estimate_usd(
    session: AsyncSession, currency: Currency, amount: Decimal
) -> tuple[Decimal | None, CurrencyUsdRate | None]:
    rate = (
        await session.execute(
            select(CurrencyUsdRate).where(CurrencyUsdRate.currency_id == currency.id)
        )
    ).scalar_one_or_none()
    if rate is None:
        return None, None
    return amount * Decimal(str(rate.usd_rate)), rate


def _normal_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        out[key] = str(value) if isinstance(value, Decimal) else value
    return out


async def _ensure_approval_or_create(
    *,
    session: AsyncSession,
    request: Request,
    admin: User,
    deal: Deal,
    currency: Currency,
    action: str,
    amount: Decimal,
    reason: str | None,
    payload: dict[str, Any],
    approval_id: int | None,
) -> AdminApprovalRequest | None:
    threshold = Decimal(str(settings.admin_deal_approval_threshold_usd))
    if threshold <= 0:
        return None
    amount_usd, rate = await _estimate_usd(session, currency, amount)
    requires_approval = amount_usd is None or amount_usd >= threshold
    if not requires_approval:
        return None

    normalized_payload = _normal_payload(payload)
    if approval_id is None:
        existing = (
            await session.execute(
                select(AdminApprovalRequest)
                .where(
                    AdminApprovalRequest.action == action,
                    AdminApprovalRequest.target_type == "deal",
                    AdminApprovalRequest.target_id == deal.id,
                    AdminApprovalRequest.status == "pending",
                    AdminApprovalRequest.payload == normalized_payload,
                )
                .options(selectinload(AdminApprovalRequest.currency))
                .with_for_update()
            )
        ).scalar_one_or_none()
        if existing is not None:
            await session.commit()
            return existing

        approval = AdminApprovalRequest(
            action=action,
            target_type="deal",
            target_id=deal.id,
            status="pending",
            requested_by_id=admin.id,
            currency_id=currency.id,
            rate_id=rate.id if rate is not None else None,
            amount=amount,
            amount_usd_estimate=amount_usd,
            reason=reason,
            payload=normalized_payload,
        )
        approval.currency = currency
        approval.rate = rate
        session.add(approval)
        await session.flush()
        await _audit(
            session=session,
            request=request,
            admin=admin,
            deal=deal,
            action="deal.approval_requested",
            reason=reason,
            payload={
                "approval_id": approval.id,
                "requested_action": action,
                "currency": currency.code,
                "amount": str(amount),
                "amount_usd_estimate": str(amount_usd) if amount_usd is not None else None,
                "threshold_usd": str(threshold),
                "rate_missing": amount_usd is None,
            },
        )
        await session.commit()
        return approval

    approval = (
        await session.execute(
            select(AdminApprovalRequest)
            .where(AdminApprovalRequest.id == approval_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if approval is None:
        raise HTTPException(404, "Approval request not found")
    if approval.status != "approved":
        raise HTTPException(409, "Approval request is not approved")
    if approval.target_type != "deal" or approval.target_id != deal.id or approval.action != action:
        raise HTTPException(400, "Approval request does not match this action")
    if approval.payload != normalized_payload:
        raise HTTPException(400, "Approval request payload does not match this action")
    if approval.requested_by_id == admin.id and approval.approved_by_id is None:
        raise HTTPException(400, "Approval request needs a second admin")
    return approval


async def _mark_approval_executed(
    approval: AdminApprovalRequest | None,
    admin: User,
) -> None:
    if approval is None:
        return
    approval.status = "executed"
    approval.executed_by_id = admin.id
    approval.executed_at = utcnow()


async def _notify_party(
    session: AsyncSession,
    user_id: int,
    title: str,
    body: str,
    deal_id: int,
    pending: list[tuple[Notification, dict[str, Any] | None]],
) -> None:
    """Stage a deal-state notification for post-commit dispatch.

    A9-M-2 — insert the notification row inside the caller's
    transaction (so it commits atomically with the deal-state flip +
    balance writes) and append the (notif, ws_payload) tuple to the
    caller's ``pending`` list. The caller fires
    ``notifier.dispatch_after_commit`` for each entry only *after*
    ``await session.commit()`` so a rolled-back force-action never
    leaks a "сделка завершена" toast to either party.
    """
    notif, ws_payload = await notifier.insert(
        session,
        user_id,
        NotificationType.deals,
        title,
        body,
        {"deal_id": deal_id},
    )
    pending.append((notif, ws_payload))


async def _dispatch_pending(
    session: AsyncSession,
    pending: list[tuple[Notification, dict[str, Any] | None]],
    *,
    event: str,
) -> None:
    """Post-commit half of the deal-action notification fan-out."""
    for notif, ws_payload in pending:
        try:
            await notifier.dispatch_after_commit(session, notif, ws_payload)
        except Exception:
            logger.exception(
                "admin deal action: post-commit dispatch failed for notif id=%s",
                notif.id,
                extra={"event": event, "notif_id": notif.id},
            )


# --------------------------------------------------------------------- listing


_STATUS_CHOICES = (
    "any",
    "cancelled",
    "pending_confirmation",
    # Audit M3 — ``pending_payment`` is reserved in ``DealStatus`` but no
    # transition writes it; dropped from the filter so the admin UI
    # doesn't surface a permanently-empty status bucket.
    "pending_topup",
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
    min_amount: Annotated[float | None, Query()] = None,
    max_amount: Annotated[float | None, Query()] = None,
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
    if min_amount is not None:
        filters.append(Deal.amount >= min_amount)
    if max_amount is not None:
        filters.append(Deal.amount <= max_amount)
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


_APPROVAL_STATUS_CHOICES = ("any", "pending", "approved", "executed", "rejected")


async def _get_approval_or_404(
    session: AsyncSession,
    approval_id: int,
    *,
    lock: bool = False,
) -> AdminApprovalRequest:
    stmt = (
        select(AdminApprovalRequest)
        .where(
            AdminApprovalRequest.id == approval_id,
            AdminApprovalRequest.target_type == "deal",
        )
        .options(selectinload(AdminApprovalRequest.currency))
    )
    if lock:
        stmt = stmt.with_for_update()
    approval = (await session.execute(stmt)).scalar_one_or_none()
    if approval is None:
        raise HTTPException(404, "Approval request not found")
    return approval


@router.get("/approvals", response_model=list[AdminApprovalOut])
async def list_deal_approvals(
    _admin: AdminUser,
    session: SessionDep,
    status: Annotated[str, Query()] = "pending",
    target_id: Annotated[int | None, Query()] = None,
) -> list[AdminApprovalOut]:
    if status not in _APPROVAL_STATUS_CHOICES:
        raise HTTPException(400, "Invalid approval status")
    stmt = (
        select(AdminApprovalRequest)
        .where(AdminApprovalRequest.target_type == "deal")
        .options(selectinload(AdminApprovalRequest.currency))
        .order_by(AdminApprovalRequest.created_at.desc(), AdminApprovalRequest.id.desc())
        .limit(200)
    )
    if status != "any":
        stmt = stmt.where(AdminApprovalRequest.status == status)
    if target_id is not None:
        stmt = stmt.where(AdminApprovalRequest.target_id == target_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [_approval_out(row) for row in rows]


@router.post("/approvals/{approval_id}/approve", response_model=AdminApprovalOut)
async def approve_deal_approval(
    approval_id: int,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminApprovalOut:
    approval = await _get_approval_or_404(session, approval_id, lock=True)
    if approval.status != "pending":
        raise HTTPException(409, "Approval request is not pending")
    if approval.requested_by_id == admin.id:
        raise HTTPException(400, "Approval request needs a second admin")

    approval.status = "approved"
    approval.approved_by_id = admin.id
    approval.approved_at = utcnow()
    await log_admin_action(
        session,
        actor=admin,
        action="deal.approval_approved",
        target_type="deal",
        target_id=approval.target_id,
        payload={"approval_id": approval.id, "requested_action": approval.action},
        request=request,
    )
    await session.commit()
    return _approval_out(approval)


@router.post("/approvals/{approval_id}/reject", response_model=AdminApprovalOut)
async def reject_deal_approval(
    approval_id: int,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminApprovalOut:
    approval = await _get_approval_or_404(session, approval_id, lock=True)
    if approval.status != "pending":
        raise HTTPException(409, "Approval request is not pending")

    approval.status = "rejected"
    approval.rejected_at = utcnow()
    await log_admin_action(
        session,
        actor=admin,
        action="deal.approval_rejected",
        target_type="deal",
        target_id=approval.target_id,
        payload={"approval_id": approval.id, "requested_action": approval.action},
        request=request,
    )
    await session.commit()
    return _approval_out(approval)


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


async def _lock_buyer_seller_balances(
    session: AsyncSession, deal: Deal, currency_id: int
) -> tuple[UserBalance, UserBalance]:
    first_id, second_id = sorted((deal.buyer_id, deal.seller_id))
    first = await lock_user_balance(session, first_id, currency_id)
    second = await lock_user_balance(session, second_id, currency_id)
    if deal.buyer_id == first_id:
        return first, second
    return second, first


async def _release_locked_to_seller(
    session: AsyncSession, deal: Deal, currency: Currency
) -> tuple[Decimal, Decimal]:
    """Move locked funds from buyer to seller, retaining commission.

    Returns ``(locked_pot, payout)`` for the audit record.
    """
    # P10 — commission is collected on the platform via the deposit
    # invoice path and never enters ``UserBalance.locked``. The
    # locked pot equals the deal principal; the seller's payout is
    # the same principal (no commission deduction here).
    decimals = currency.decimals
    amt = quantize_money(Decimal(str(deal.amount or 0)), decimals)
    locked = amt
    payout = amt

    # Lock both rows in the same order as ``services_deals._release_to``.
    # Opposite-direction deals between the same users can otherwise acquire
    # buyer/seller locks in opposite order and deadlock under admin force flows.
    buyer_balance, seller_balance = await _lock_buyer_seller_balances(session, deal, currency.id)
    buyer_before_amount = Decimal(str(buyer_balance.amount))
    buyer_before_locked = Decimal(str(buyer_balance.locked))
    buyer_balance.locked = max(Decimal(0), Decimal(str(buyer_balance.locked)) - locked)
    seller_before_amount = Decimal(str(seller_balance.amount))
    seller_before_locked = Decimal(str(seller_balance.locked))
    seller_balance.amount = Decimal(str(seller_balance.amount)) + payout
    record_balance_ledger(
        session,
        buyer_balance,
        before_amount=buyer_before_amount,
        before_locked=buyer_before_locked,
        event_type="admin_deal.force_release.debit",
        source_type="deal",
        source_id=deal.id,
    )
    record_balance_ledger(
        session,
        seller_balance,
        before_amount=seller_before_amount,
        before_locked=seller_before_locked,
        event_type="admin_deal.force_release.credit",
        source_type="deal",
        source_id=deal.id,
    )
    return locked, payout


async def _refund_locked_to_buyer(
    session: AsyncSession, deal: Deal, currency: Currency
) -> tuple[Decimal, Decimal]:
    """Unlock locked funds and credit *only the principal* back to the buyer.

    Per spec, commission is charged on every deal regardless of outcome,
    so a buyer-paid commission stays in the platform pool on refund.
    Returns ``(locked_pot, refunded_principal)``.
    """
    # P10 — commission no longer rides on ``UserBalance.locked``;
    # refund the entire locked principal back to the buyer 1:1.
    decimals = currency.decimals
    amt = quantize_money(Decimal(str(deal.amount or 0)), decimals)
    locked = amt
    refunded = amt

    # CRIT #1 — ``FOR UPDATE`` lock; see ``_release_locked_to_seller``.
    buyer_balance = await lock_user_balance(session, deal.buyer_id, currency.id)
    before_amount = Decimal(str(buyer_balance.amount))
    before_locked = Decimal(str(buyer_balance.locked))
    buyer_balance.locked = max(Decimal(0), Decimal(str(buyer_balance.locked)) - locked)
    buyer_balance.amount = Decimal(str(buyer_balance.amount)) + refunded
    record_balance_ledger(
        session,
        buyer_balance,
        before_amount=before_amount,
        before_locked=before_locked,
        event_type="admin_deal.force_refund",
        source_type="deal",
        source_id=deal.id,
    )
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
    # P10 — the split operates on the locked principal only; the
    # platform's commission was already collected via the deposit
    # invoice (and is not refundable per spec).
    decimals = currency.decimals
    amt = quantize_money(Decimal(str(deal.amount or 0)), decimals)
    locked = amt
    buyer_share = quantize_money(amt * Decimal(str(buyer_percent)) / Decimal(100), decimals)
    seller_share = amt - buyer_share

    # Lock both rows in the same order as ``services_deals._release_to``.
    # See ``_release_locked_to_seller`` for the deadlock geometry.
    buyer_balance, seller_balance = await _lock_buyer_seller_balances(session, deal, currency.id)
    buyer_before_amount = Decimal(str(buyer_balance.amount))
    buyer_before_locked = Decimal(str(buyer_balance.locked))
    buyer_balance.locked = max(Decimal(0), Decimal(str(buyer_balance.locked)) - locked)
    buyer_balance.amount = Decimal(str(buyer_balance.amount)) + buyer_share
    seller_before_amount = Decimal(str(seller_balance.amount))
    seller_before_locked = Decimal(str(seller_balance.locked))
    seller_balance.amount = Decimal(str(seller_balance.amount)) + seller_share
    record_balance_ledger(
        session,
        buyer_balance,
        before_amount=buyer_before_amount,
        before_locked=buyer_before_locked,
        event_type="admin_deal.split.buyer",
        source_type="deal",
        source_id=deal.id,
        meta={"buyer_percent": str(buyer_percent)},
    )
    record_balance_ledger(
        session,
        seller_balance,
        before_amount=seller_before_amount,
        before_locked=seller_before_locked,
        event_type="admin_deal.split.seller",
        source_type="deal",
        source_id=deal.id,
        meta={"buyer_percent": str(buyer_percent)},
    )
    return locked, buyer_share, seller_share


def _is_active_for_money_movement(status: DealStatus) -> bool:
    """A deal still has locked money iff it hasn't terminated yet.

    Audit M3 — ``pending_payment`` is omitted because no transition
    writes it; including it here was dead branch coverage that
    confused readers into thinking a separate "awaiting payment"
    state was wired up.
    """
    return status in (
        DealStatus.pending_confirmation,
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
    # CRIT — gate on the active-money-movement allow-list, not the
    # terminal-state deny-list. The deny-list misses
    # ``pending_topup``: buyer hasn't paid the deposit invoice yet
    # so ``UserBalance.locked`` is zero for the principal, and the
    # release path then credits the seller from nothing
    # (``buyer.locked = max(0, 0 - amt) = 0`` while
    # ``seller.amount += amt``). Same hazard applies to ``pending``
    # (no escrow yet either).
    if not _is_active_for_money_movement(deal.status):
        raise HTTPException(400, "Сделка не в активной фазе расчётов")
    if deal.currency_id is None or deal.amount is None:
        raise HTTPException(400, "У сделки не задана валюта")
    currency = await session.get(Currency, deal.currency_id)
    # M-1: ``assert`` is stripped under ``python -O``; raise explicitly.
    if currency is None:
        raise HTTPException(500, "Внутренняя ошибка: валюта сделки не найдена")

    amount_native = quantize_money(Decimal(str(deal.amount or 0)), currency.decimals)
    approval = await _ensure_approval_or_create(
        session=session,
        request=request,
        admin=admin,
        deal=deal,
        currency=currency,
        action="deal.force_release",
        amount=amount_native,
        reason=body.reason,
        payload={"currency": currency.code, "amount": str(amount_native)},
        approval_id=body.approval_id,
    )
    if approval is not None and approval.status == "pending":
        return AdminDealActionResult(
            deal=await _to_detail(session, deal),
            pending_approval=_approval_out(approval),
        )

    before_status = deal.status.value
    locked, payout = await _release_locked_to_seller(session, deal, currency)
    deal.status = DealStatus.resolved_for_seller
    deal.completed_at = utcnow()
    deal.arbitration_resolved_by = admin.id
    deal.arbitration_resolution = "seller"
    if deal.arbitration_resolved_at is None:
        deal.arbitration_resolved_at = utcnow()

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
            # M-23: keep Numeric(28,8) precision in the JSONB audit trail.
            "locked": str(locked),
            "payout": str(payout),
            "approval_id": approval.id if approval is not None else None,
        },
    )
    await _mark_approval_executed(approval, admin)
    # A9-M-2 — stage both party notifications before commit, dispatch after.
    pending: list[tuple[Notification, dict[str, Any] | None]] = []
    await _notify_party(
        session,
        deal.seller_id,
        "Сделка завершена администратором",
        (
            f"Сделка #{deal.id} завершена в вашу пользу. "
            f"Сумма {payout} {currency.code} зачислена на баланс."
        ),
        deal.id,
        pending,
    )
    await _notify_party(
        session,
        deal.buyer_id,
        "Сделка завершена администратором",
        f"Сделка #{deal.id} завершена в пользу продавца.",
        deal.id,
        pending,
    )
    await session.commit()
    await _dispatch_pending(session, pending, event="deal.force_release.dispatch.failed")
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
    # CRIT — see ``force_release`` for the rationale; the active-
    # phase allow-list is the only correct gate for money movement.
    if not _is_active_for_money_movement(deal.status):
        raise HTTPException(400, "Сделка не в активной фазе расчётов")
    if deal.currency_id is None or deal.amount is None:
        raise HTTPException(400, "У сделки не задана валюта")
    currency = await session.get(Currency, deal.currency_id)
    # M-1: ``assert`` is stripped under ``python -O``; raise explicitly.
    if currency is None:
        raise HTTPException(500, "Внутренняя ошибка: валюта сделки не найдена")

    amount_native = quantize_money(Decimal(str(deal.amount or 0)), currency.decimals)
    approval = await _ensure_approval_or_create(
        session=session,
        request=request,
        admin=admin,
        deal=deal,
        currency=currency,
        action="deal.force_refund",
        amount=amount_native,
        reason=body.reason,
        payload={"currency": currency.code, "amount": str(amount_native)},
        approval_id=body.approval_id,
    )
    if approval is not None and approval.status == "pending":
        return AdminDealActionResult(
            deal=await _to_detail(session, deal),
            pending_approval=_approval_out(approval),
        )

    before_status = deal.status.value
    locked, refunded = await _refund_locked_to_buyer(session, deal, currency)
    deal.status = DealStatus.resolved_for_buyer
    deal.completed_at = utcnow()
    deal.arbitration_resolved_by = admin.id
    deal.arbitration_resolution = "buyer"
    if deal.arbitration_resolved_at is None:
        deal.arbitration_resolved_at = utcnow()

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
            # M-23: keep Numeric(28,8) precision in the JSONB audit trail.
            "locked": str(locked),
            "refunded": str(refunded),
            "approval_id": approval.id if approval is not None else None,
        },
    )
    await _mark_approval_executed(approval, admin)
    pending: list[tuple[Notification, dict[str, Any] | None]] = []
    await _notify_party(
        session,
        deal.buyer_id,
        "Сделка возвращена администратором",
        (
            f"Сделка #{deal.id} закрыта в вашу пользу, "
            f"возвращено {refunded} {currency.code} (комиссия удержана)."
        ),
        deal.id,
        pending,
    )
    await _notify_party(
        session,
        deal.seller_id,
        "Сделка возвращена администратором",
        f"Сделка #{deal.id} закрыта в пользу покупателя.",
        deal.id,
        pending,
    )
    await session.commit()
    await _dispatch_pending(session, pending, event="deal.force_refund.dispatch.failed")
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
    # CRIT — see ``force_release`` for the rationale; the active-
    # phase allow-list is the only correct gate for money movement.
    if not _is_active_for_money_movement(deal.status):
        raise HTTPException(400, "Сделка не в активной фазе расчётов")
    if deal.currency_id is None or deal.amount is None:
        raise HTTPException(400, "У сделки не задана валюта")
    currency = await session.get(Currency, deal.currency_id)
    # M-1: ``assert`` is stripped under ``python -O``; raise explicitly.
    if currency is None:
        raise HTTPException(500, "Внутренняя ошибка: валюта сделки не найдена")

    amount_native = quantize_money(Decimal(str(deal.amount or 0)), currency.decimals)
    approval = await _ensure_approval_or_create(
        session=session,
        request=request,
        admin=admin,
        deal=deal,
        currency=currency,
        action="deal.split",
        amount=amount_native,
        reason=body.reason,
        payload={
            "currency": currency.code,
            "amount": str(amount_native),
            "buyer_percent": str(body.buyer_percent),
        },
        approval_id=body.approval_id,
    )
    if approval is not None and approval.status == "pending":
        return AdminDealActionResult(
            deal=await _to_detail(session, deal),
            pending_approval=_approval_out(approval),
        )

    before_status = deal.status.value
    locked, buyer_share, seller_share = await _split_locked(
        session, deal, currency, float(body.buyer_percent)
    )
    deal.status = (
        DealStatus.resolved_for_buyer
        if body.buyer_percent >= 50
        else DealStatus.resolved_for_seller
    )
    deal.completed_at = utcnow()
    deal.arbitration_resolved_by = admin.id
    deal.arbitration_resolution = "buyer" if body.buyer_percent >= 50 else "seller"
    if deal.arbitration_resolved_at is None:
        deal.arbitration_resolved_at = utcnow()

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
            # M-23: keep Numeric(28,8) precision in the JSONB audit trail.
            "buyer_share": str(buyer_share),
            "seller_share": str(seller_share),
            "locked": str(locked),
            "approval_id": approval.id if approval is not None else None,
        },
    )
    await _mark_approval_executed(approval, admin)
    pending: list[tuple[Notification, dict[str, Any] | None]] = []
    await _notify_party(
        session,
        deal.buyer_id,
        "Сделка разделена администратором",
        f"По сделке #{deal.id} вам возвращено {buyer_share} {currency.code}.",
        deal.id,
        pending,
    )
    await _notify_party(
        session,
        deal.seller_id,
        "Сделка разделена администратором",
        f"По сделке #{deal.id} вам начислено {seller_share} {currency.code}.",
        deal.id,
        pending,
    )
    await session.commit()
    await _dispatch_pending(session, pending, event="deal.split.dispatch.failed")
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
    pending: list[tuple[Notification, dict[str, Any] | None]] = []
    for recipient_id in (deal.buyer_id, deal.seller_id):
        await _notify_party(
            session,
            recipient_id,
            "Открыт арбитраж",
            f"По сделке #{deal.id} открыт арбитраж администратором.",
            deal.id,
            pending,
        )
    await session.commit()
    await _dispatch_pending(session, pending, event="deal.force_arbitration.dispatch.failed")
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
    pending: list[tuple[Notification, dict[str, Any] | None]] = []
    if body.arbiter_id is not None:
        await _notify_party(
            session,
            body.arbiter_id,
            "Назначен арбитр",
            f"Вам назначена сделка #{deal.id} для арбитража.",
            deal.id,
            pending,
        )
    await session.commit()
    await _dispatch_pending(session, pending, event="deal.assign_arbiter.dispatch.failed")
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

    # M-23: store amount columns as strings in the JSONB audit payload so
    # the full ``Numeric(28,8)`` precision survives. The previous
    # ``float(...)`` cast silently dropped trailing satoshi on large
    # BTC deals, which made the snapshot unsafe to use for reconciliation.
    snapshot: dict[str, object] = {
        "id": deal.id,
        "status": deal.status.value,
        "buyer_id": deal.buyer_id,
        "seller_id": deal.seller_id,
        "currency": currency.code if currency else None,
        "amount": str(deal.amount) if deal.amount is not None else None,
        "commission_amount": (
            str(deal.commission_amount) if deal.commission_amount is not None else None
        ),
        "commission_paid": bool(deal.commission_paid),
        "created_at": deal.created_at.isoformat() if deal.created_at else None,
    }
    refunded: Decimal | None = None
    if currency is not None and _is_active_for_money_movement(deal.status):
        # Delete is the admin nuclear option — returns the full locked
        # pot (including any commission share) because the deal row
        # disappears from the treasury accrual query too. This is the
        # one path that does NOT retain commission.
        decimals = currency.decimals
        amt = quantize_money(Decimal(str(deal.amount or 0)), decimals)
        # P10 — ``UserBalance.locked`` carries only the principal.
        locked_pot = amt
        # CRIT #1 — ``FOR UPDATE`` lock so the refund branch can’t
        # be read-modify-written by a concurrent admin/user action
        # on the same buyer balance.
        buyer_balance = await lock_user_balance(session, deal.buyer_id, currency.id)
        # M-23: assign ``Decimal`` directly to the ``Numeric(28,8)``
        # columns. The previous ``float(...)`` wrapper round-tripped
        # through float64 and dropped the last few satoshi units on
        # large BTC balances; this matches the canonical pattern in
        # ``services_deals.py``.
        buyer_balance.locked = max(Decimal(0), Decimal(str(buyer_balance.locked)) - locked_pot)
        buyer_balance.amount = Decimal(str(buyer_balance.amount)) + locked_pot
        refunded = locked_pot
        # Audit payload stays JSON-safe via ``str`` so the trail keeps
        # full Decimal precision (the JSON encoder used by the audit
        # log will store the value verbatim).
        snapshot["refunded"] = str(refunded)

    # Clean up dependent rows: messages reference the deal via FK.
    # Gather media files attached to messages to clean them up from DB and disk
    messages = (
        await session.execute(
            select(DealMessage.attachments_json).where(DealMessage.deal_id == deal.id)
        )
    ).scalars().all()

    all_media_ids: set[int] = set()
    from ..deal_messages import _parse_attachment_ids
    for attachments_json in messages:
        all_media_ids.update(_parse_attachment_ids(attachments_json))

    paths_to_delete: list[Path] = []
    if all_media_ids:
        media_rows = (
            await session.execute(
                select(Media).where(Media.id.in_(all_media_ids))
            )
        ).scalars().all()

        media_root = Path(settings.media_root).expanduser().resolve()
        for m in media_rows:
            filename = m.url.split("/")[-1]
            file_path = media_root / m.kind / filename
            paths_to_delete.append(file_path)

        await session.execute(Media.__table__.delete().where(Media.id.in_(all_media_ids)))

        def delete_files(paths):
            for p in paths:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    logger.exception("Failed to delete orphaned media file: %s", p)

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
    await session.flush()

    pending: list[tuple[Notification, dict[str, Any] | None]] = []
    for recipient_id, role in ((buyer_id, "buyer"), (seller_id, "seller")):
        body_text = f"Сделка #{deal_id_local} удалена администратором." + (
            f" Вам возвращено {refunded} {currency.code}."
            if (refunded is not None and currency is not None and role == "buyer")
            else ""
        )
        await _notify_party(
            session,
            recipient_id,
            "Сделка удалена",
            body_text,
            deal_id_local,
            pending,
        )
    await session.commit()
    if paths_to_delete:
        await asyncio.to_thread(delete_files, paths_to_delete)
    await _dispatch_pending(session, pending, event="deal.delete.dispatch.failed")

    return {
        "deleted": True,
        "deal_id": deal_id_local,
        "refunded": str(refunded) if refunded is not None else None,
    }
