"""Admin arbitration queue — ``/api/admin/arbitration``.

Two distinct concerns:

* Listing the queue split into three buckets: **new** (no arbiter
  assigned yet), **in_progress** (someone is working it), **closed**
  (resolved). Arbiters and admins both call the same endpoint; admins
  see every deal, arbiters see only ones assigned to them or
  unassigned.
* "Взять в работу" — atomically self-assign an unclaimed dispute via
  a single ``UPDATE … WHERE arbitration_resolved_by IS NULL`` so two
  arbiters can't claim the same deal.

The split-decision and force-release/refund endpoints live in
``admin/deals.py`` — arbiters reuse them too because the action is
identical regardless of who triggers it.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, or_, select, update

from ... import notifier
from ...admin_audit import log_admin_action
from ...deps import AdminOrArbiterUser, SessionDep
from ...models import Deal, DealStatus, Notification, NotificationType
from ...rate_limit import rate_limit
from ...schemas import (
    AdminArbitrationCounters,
    AdminArbitrationListOut,
)
from ...time_utils import utcnow
from .deals import _to_list_item

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/arbitration",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin", limit=600, window=60))],
)


_CLOSED_STATES = (
    DealStatus.resolved_for_buyer,
    DealStatus.resolved_for_seller,
)


def _queue_filter(queue: str, user_id: int | None, is_admin: bool):
    if queue == "new":
        cond = and_(
            Deal.status == DealStatus.arbitration,
            Deal.arbitration_resolved_by.is_(None),
        )
    elif queue == "in_progress":
        cond = and_(
            Deal.status == DealStatus.arbitration,
            Deal.arbitration_resolved_by.is_not(None),
        )
    elif queue == "closed":
        cond = Deal.status.in_(_CLOSED_STATES)
    else:
        raise HTTPException(400, "Неверная очередь")

    if is_admin:
        return cond
    # arbiters see only unassigned (so they can claim) or their own.
    return and_(
        cond,
        or_(Deal.arbitration_resolved_by.is_(None), Deal.arbitration_resolved_by == user_id),
    )


@router.get("", response_model=AdminArbitrationListOut)
async def list_arbitration(
    user: AdminOrArbiterUser,
    session: SessionDep,
    queue: Annotated[Literal["new", "in_progress", "closed"], Query()] = "new",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminArbitrationListOut:
    is_admin = bool(user.is_admin)
    cond = _queue_filter(queue, user.id, is_admin)

    stmt = (
        select(Deal)
        .where(cond)
        .order_by(Deal.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await session.execute(stmt)).scalars().all()

    async def _count(q: str) -> int:
        c_cond = _queue_filter(q, user.id, is_admin)
        return int(
            (
                await session.execute(select(func.count()).select_from(Deal).where(c_cond))
            ).scalar_one()
            or 0
        )

    counters = AdminArbitrationCounters(
        new=await _count("new"),
        in_progress=await _count("in_progress"),
        closed=await _count("closed"),
    )

    return AdminArbitrationListOut(
        items=[_to_list_item(d) for d in rows],
        counters=counters,
        queue=queue,
    )


@router.post("/{deal_id}/claim", status_code=200)
async def claim_arbitration(
    deal_id: int,
    user: AdminOrArbiterUser,
    session: SessionDep,
    request: Request,
) -> dict:
    """Atomically claim a dispute.

    Implemented as ``UPDATE … WHERE arbitration_resolved_by IS NULL AND
    status='arbitration'`` so two concurrent arbiters can never both
    claim the same deal: the loser sees ``rowcount=0`` and gets a 409.
    """
    result = await session.execute(
        update(Deal)
        .where(
            Deal.id == deal_id,
            Deal.status == DealStatus.arbitration,
            Deal.arbitration_resolved_by.is_(None),
        )
        .values(arbitration_resolved_by=user.id)
    )
    if result.rowcount == 0:
        # Either deal doesn't exist, isn't in arbitration, or already claimed.
        deal = await session.get(Deal, deal_id)
        if deal is None:
            raise HTTPException(404, "Сделка не найдена")
        if deal.status != DealStatus.arbitration:
            raise HTTPException(400, "Сделка не находится в арбитраже")
        raise HTTPException(409, "Сделка уже взята в работу другим арбитром")

    deal = await session.get(Deal, deal_id)
    # M-1: ``assert`` is stripped under ``python -O``; the row was just
    # locked by the previous UPDATE, but raise explicitly to keep the
    # invariant under ``-O`` as well.
    if deal is None:
        raise HTTPException(500, "Внутренняя ошибка: сделка пропала после claim")
    await log_admin_action(
        session,
        actor=user,
        action="arbitration.claim",
        target_type="deal",
        target_id=deal.id,
        reason=None,
        payload={"arbiter_id": user.id},
        request=request,
    )
    # A9-M-2 — split-API: persist both party notifications atomically
    # with the claim-row update + audit row, dispatch WS/DM after
    # commit so a rolled-back claim never leaks "арбитр назначен"
    # toasts for a deal that's still unclaimed.
    pending: list[tuple[Notification, dict[str, Any] | None]] = []
    for recipient_id in (deal.buyer_id, deal.seller_id):
        notif, ws_payload = await notifier.insert(
            session,
            recipient_id,
            NotificationType.deals,
            "Назначен арбитр",
            f"По сделке #{deal.id} назначен арбитр.",
            {"deal_id": deal.id},
        )
        pending.append((notif, ws_payload))
    await session.commit()
    for notif, ws_payload in pending:
        try:
            await notifier.dispatch_after_commit(session, notif, ws_payload)
        except Exception:
            logger.exception(
                "claim_arbitration: post-commit dispatch failed for notif id=%s",
                notif.id,
                extra={
                    "event": "claim_arbitration.dispatch.failed",
                    "notif_id": notif.id,
                },
            )

    return {
        "claimed": True,
        "deal_id": deal.id,
        "arbiter_id": user.id,
        "claimed_at": utcnow().isoformat(),
    }
