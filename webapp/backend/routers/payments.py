from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from routers.utils.cryptobot import create_add_money_request
from utils.database.extras import WebDB
from utils.database.models import Users
from utils.notifier import notifier
from webapp.backend.deps import get_current_user
from webapp.backend.schemas import (
    DepositCreate,
    DepositOut,
    InvoiceOut,
    WithdrawCreate,
)

router = APIRouter(prefix="/api/payments", tags=["payments"])
logger = logging.getLogger(__name__)


@router.get("/deposit", response_model=list[DepositOut])
async def list_deposits(user: Users = Depends(get_current_user)) -> list[DepositOut]:
    rows = await run_in_threadpool(WebDB().list_deposits, user.username)
    return [DepositOut(**row) for row in rows]


@router.post("/deposit", response_model=DepositOut, status_code=201)
async def create_deposit(payload: DepositCreate, user: Users = Depends(get_current_user)) -> DepositOut:
    row = await run_in_threadpool(WebDB().create_deposit, user.username, payload.amount)
    await notifier.push(
        user.username,
        type_="deposits",
        title="Депозит обновлён",
        body=f"Активный депозит увеличен на ${payload.amount:.2f}",
        payload={"deposit_id": row["id"]},
        send_telegram=False,
    )
    return DepositOut(**row, created_at=row.get("created_at", ""), released_at=row.get("released_at"))


@router.post("/deposit/invoice", response_model=InvoiceOut)
async def deposit_invoice(payload: DepositCreate, _: Users = Depends(get_current_user)) -> InvoiceOut:
    try:
        invoice = await create_add_money_request(payload.amount)
    except Exception as exc:  # noqa: BLE001
        logger.exception("CryptoBot invoice failed")
        raise HTTPException(status_code=502, detail=f"CryptoBot error: {exc}")
    return InvoiceOut(
        invoice_id=getattr(invoice, "invoice_id", "") or getattr(invoice, "id", ""),
        pay_url=getattr(invoice, "pay_url", "") or getattr(invoice, "bot_invoice_url", ""),
        amount=payload.amount,
        asset="USDT",
    )


@router.post("/withdraw", status_code=202)
async def withdraw(payload: WithdrawCreate, user: Users = Depends(get_current_user)) -> dict:
    if user.balance < payload.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")
    # Queue a withdraw request — admins approve via the existing bot router.
    from utils.database.db import DB

    request_id = await DB().create_withdraw_request(user.user_id, payload.amount)
    user.balance -= payload.amount
    await run_in_threadpool(user.save)
    return {"request_id": request_id, "status": "pending"}
