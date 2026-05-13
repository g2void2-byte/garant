from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from routers.utils.cryptobot import check_invoice, create_add_money_request
from utils.database.db import DB
from utils.database.extras import WebDB
from utils.database.models import Users
from utils.notifier import notifier
from webapp.backend.deps import get_current_user
from webapp.backend.schemas import (
    DepositCreate,
    DepositOut,
    InvoiceOut,
    InvoiceStatusOut,
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


@router.get("/deposit/invoice/{invoice_id}", response_model=InvoiceStatusOut)
async def deposit_invoice_status(
    invoice_id: str, user: Users = Depends(get_current_user)
) -> InvoiceStatusOut:
    """Poll CryptoBot for invoice status. On the first "paid" hit we credit
    the user's balance, record the invoice locally and push a notification.
    Subsequent calls return the same status without double-crediting because
    we deduplicate on `id_operation` (the CryptoBot invoice id).
    """
    try:
        invoices = await check_invoice(invoice_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("CryptoBot status check failed")
        raise HTTPException(status_code=502, detail=f"CryptoBot error: {exc}")
    if not invoices:
        raise HTTPException(status_code=404, detail="Invoice not found")
    inv = invoices[0]
    status_str = getattr(inv, "status", "") or ""
    paid_amount = float(getattr(inv, "paid_amount", 0) or 0)
    db = DB()
    credited = False
    if status_str == "paid":
        already = await run_in_threadpool(WebDB().has_invoice_record, int(invoice_id))
        if not already:
            await db.add_balance_by_username(user.username, paid_amount)
            await db.add_invoice(user.user_id, paid_amount, int(invoice_id))
            credited = True
            await notifier.push(
                user.username,
                type_="deposits",
                title="Баланс пополнен",
                body=f"На баланс зачислено ${paid_amount:.2f} (CryptoBot #{invoice_id})",
                payload={"invoice_id": invoice_id, "amount": paid_amount},
                send_telegram=False,
            )
    return InvoiceStatusOut(
        invoice_id=invoice_id,
        status=status_str,
        paid_amount=paid_amount,
        credited=credited,
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
