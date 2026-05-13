from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from routers.utils.status_deals import (
    ARBITRAGE,
    CONFIRMED,
    FAILED,
    SUCCESS,
    WAIT_CONFIRM,
    WAIT_FINAL_CONFIRM,
)
from utils.database.db import DB
from utils.database.extras import WebDB
from utils.database.models import Arbitrs, Deals, Users
from utils.notifier import notifier
from webapp.backend.deps import get_current_user
from webapp.backend.schemas import DealCreate, DealOut

router = APIRouter(prefix="/api/deals", tags=["deals"])


@router.get("", response_model=list[DealOut])
async def list_deals(
    role: str = Query(default="all"),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: Users = Depends(get_current_user),
) -> list[DealOut]:
    rows = await run_in_threadpool(
        WebDB().list_user_deals, user.username, role, status, limit, offset
    )
    return [DealOut(**row) for row in rows]


@router.get("/{deal_id}", response_model=DealOut)
async def get_deal(deal_id: int, user: Users = Depends(get_current_user)) -> DealOut:
    rows = await run_in_threadpool(
        WebDB().list_user_deals, user.username, "all", None, 1000, 0
    )
    for row in rows:
        if row["id"] == deal_id:
            return DealOut(**row)
    raise HTTPException(status_code=404, detail="Deal not found")


@router.post("", response_model=DealOut, status_code=201)
async def create_deal(payload: DealCreate, user: Users = Depends(get_current_user)) -> DealOut:
    counterparty = payload.counterparty.lstrip("@").lower()
    if counterparty == user.username:
        raise HTTPException(status_code=400, detail="Cannot deal with yourself")
    other = await DB().get_user_by_username(counterparty)
    if other is None:
        raise HTTPException(status_code=404, detail="Counterparty not registered")
    if payload.role == "buyer":
        buyer, seller = user.username, counterparty
    else:
        buyer, seller = counterparty, user.username
    deal = await DB().create_deal(
        buyer=buyer,
        seller=seller,
        sum=payload.sum,
        description=payload.description,
        pay_comission=payload.pay_comission,
        status=WAIT_CONFIRM,
    )
    await notifier.push(
        counterparty,
        type_="deals",
        title="Новая сделка",
        body=f"@{user.username} предложил(а) сделку на ${payload.sum:.2f}",
        payload={"deal_id": deal.id},
    )
    return DealOut(
        id=deal.id,
        buyer=deal.buyer,
        seller=deal.seller,
        sum=float(deal.sum),
        description=deal.description,
        pay_comission=deal.pay_comission,
        status=deal.status,
        confirm_buyer=False,
        confirm_seller=False,
        role="buyer" if deal.buyer == user.username else "seller",
        created_at=deal.created_at.isoformat() if deal.created_at else None,
    )


@router.post("/{deal_id}/confirm", response_model=DealOut)
async def confirm_deal(deal_id: int, user: Users = Depends(get_current_user)) -> DealOut:
    deal = await DB().get_deal_by_id(deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    if user.username not in (deal.buyer, deal.seller):
        raise HTTPException(status_code=403, detail="Forbidden")
    if deal.status != WAIT_CONFIRM:
        raise HTTPException(status_code=400, detail="Deal is not awaiting confirmation")
    await DB().update_deal_confirm(deal_id, user.username)
    # Re-fetch deal so we see the freshly-written confirm flag.
    deal = await DB().get_deal_by_id(deal_id)
    if deal.confirm_buyer and deal.confirm_seller:
        await DB().update_status_deal(deal_id, CONFIRMED)
    other = deal.seller if user.username == deal.buyer else deal.buyer
    await notifier.push(
        other,
        type_="deals",
        title="Сделка подтверждена" if not (deal.confirm_buyer and deal.confirm_seller) else "Сделка готова к исполнению",
        body=f"@{user.username} подтвердил(а) сделку #{deal_id}",
        payload={"deal_id": deal_id},
    )
    return await _deal_as_response(deal_id, user.username)


@router.post("/{deal_id}/complete", response_model=DealOut)
async def complete_deal(deal_id: int, user: Users = Depends(get_current_user)) -> DealOut:
    deal = await DB().get_deal_by_id(deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    if user.username != deal.buyer:
        raise HTTPException(status_code=403, detail="Only the buyer can complete a deal")
    if deal.status not in (CONFIRMED, WAIT_FINAL_CONFIRM):
        raise HTTPException(status_code=400, detail="Deal not in completable state")
    # Credit the seller — mirrors routers/user/manage_deal.py:78-91. If the
    # buyer pays the commission the seller gets the full sum, otherwise
    # commission is deducted from the seller payout.
    percent_deal = await DB().get_percent_deal()
    if deal.pay_comission == "buyer":
        payout = float(deal.sum)
    else:
        payout = float(deal.sum) - (float(deal.sum) / 100 * float(percent_deal))
    await DB().update_status_deal(deal_id, SUCCESS)
    await DB().add_balance_by_username(deal.seller, payout)
    other = deal.seller
    await notifier.push(
        other,
        type_="deals",
        title="Сделка завершена",
        body=(
            f"@{user.username} подтвердил(а) исполнение сделки #{deal_id}. "
            f"На баланс зачислено ${payout:.2f}."
        ),
        payload={"deal_id": deal_id, "amount": payout},
    )
    return await _deal_as_response(deal_id, user.username)


@router.post("/{deal_id}/cancel", response_model=DealOut)
async def cancel_deal(deal_id: int, user: Users = Depends(get_current_user)) -> DealOut:
    deal = await DB().get_deal_by_id(deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    if user.username not in (deal.buyer, deal.seller):
        raise HTTPException(status_code=403, detail="Forbidden")
    if deal.status not in (WAIT_CONFIRM,):
        raise HTTPException(status_code=400, detail="Deal can no longer be cancelled")
    await DB().update_status_deal(deal_id, FAILED)
    other = deal.seller if user.username == deal.buyer else deal.buyer
    await notifier.push(
        other,
        type_="deals",
        title="Сделка отменена",
        body=f"@{user.username} отменил(а) сделку #{deal_id}",
        payload={"deal_id": deal_id},
    )
    return await _deal_as_response(deal_id, user.username)


@router.post("/{deal_id}/arbitrate", response_model=DealOut)
async def arbitrate_deal(
    deal_id: int,
    reason: str | None = Query(default=None),
    user: Users = Depends(get_current_user),
) -> DealOut:
    deal = await DB().get_deal_by_id(deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    if user.username not in (deal.buyer, deal.seller):
        raise HTTPException(status_code=403, detail="Forbidden")
    await DB().update_status_deal(deal_id, ARBITRAGE)
    await run_in_threadpool(
        Arbitrs.create,
        deal_id=deal_id,
        initiator=user.username,
        reason=reason or "—",
    )
    other = deal.seller if user.username == deal.buyer else deal.buyer
    await notifier.push(
        other,
        type_="deals",
        title="Открыт арбитраж",
        body=f"@{user.username} открыл(а) спор по сделке #{deal_id}",
        payload={"deal_id": deal_id},
    )
    return await _deal_as_response(deal_id, user.username)


async def _deal_as_response(deal_id: int, username: str) -> DealOut:
    deal: Deals = await DB().get_deal_by_id(deal_id)
    return DealOut(
        id=deal.id,
        buyer=deal.buyer,
        seller=deal.seller,
        sum=float(deal.sum),
        description=deal.description,
        pay_comission=deal.pay_comission,
        status=deal.status,
        confirm_buyer=bool(deal.confirm_buyer),
        confirm_seller=bool(deal.confirm_seller),
        role="buyer" if deal.buyer == username else "seller",
        created_at=deal.created_at.isoformat() if getattr(deal, "created_at", None) else None,
    )
