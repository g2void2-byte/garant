from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..config import settings
from ..cryptopay import CryptoPay, CryptoPayError
from ..deps import CurrentUser, SessionDep
from ..models import Invoice, InvoiceProvider, InvoiceStatus
from ..schemas import DepositReq, InvoiceCreateReq, InvoiceOut, InvoiceStatusOut, WithdrawReq
from ..services import credit_invoice

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["payments"])


@router.get("/deposit", response_model=list[InvoiceStatusOut])
async def list_deposits(user: CurrentUser, session: SessionDep):
    stmt = (
        select(Invoice)
        .where(Invoice.owner_id == user.id)
        .order_by(Invoice.created_at.desc())
        .limit(50)
    )
    result = await session.execute(stmt)
    return [
        InvoiceStatusOut(
            id=inv.id,
            amount=float(inv.amount),
            status=inv.status.value,
            created_at=inv.created_at,
            paid_at=inv.paid_at,
        )
        for inv in result.scalars().all()
    ]


@router.post("/deposit/invoice", response_model=InvoiceOut)
async def create_deposit_invoice(
    body: InvoiceCreateReq, user: CurrentUser, session: SessionDep,
):
    if not settings.cryptobot_token or settings.cryptobot_token.startswith("000"):
        raise HTTPException(502, "CryptoBot не настроен")

    try:
        async with CryptoPay(
            settings.cryptobot_token, testnet=settings.cryptobot_testnet
        ) as crypto:
            invoice = await crypto.create_invoice(asset="USDT", amount=body.amount)
    except CryptoPayError as e:
        logger.error("CryptoBot error: %s", e)
        raise HTTPException(502, f"Ошибка CryptoBot: {e}")

    db_invoice = Invoice(
        owner_id=user.id,
        provider=InvoiceProvider.cryptobot,
        provider_invoice_id=str(invoice.invoice_id),
        amount=body.amount,
        status=InvoiceStatus.pending,
    )
    session.add(db_invoice)
    await session.commit()
    await session.refresh(db_invoice)

    return InvoiceOut(
        invoice_id=str(invoice.invoice_id),
        pay_url=invoice.pay_url,
        amount=float(body.amount),
        asset="USDT",
    )


@router.get("/deposit/invoice/{invoice_id}", response_model=InvoiceStatusOut)
async def check_invoice(invoice_id: int, user: CurrentUser, session: SessionDep):
    inv = await session.get(Invoice, invoice_id)
    if not inv or inv.owner_id != user.id:
        raise HTTPException(404, "Инвойс не найден")

    if inv.status == InvoiceStatus.pending and settings.cryptobot_token:
        try:
            async with CryptoPay(
                settings.cryptobot_token, testnet=settings.cryptobot_testnet
            ) as crypto:
                checks = await crypto.get_invoices(
                    invoice_ids=[int(inv.provider_invoice_id)]
                )
            if checks and checks[0].status == "paid":
                inv = await credit_invoice(session, inv)
        except CryptoPayError as e:
            logger.warning("CryptoBot poll error: %s", e)

    return InvoiceStatusOut(
        id=inv.id,
        amount=float(inv.amount),
        status=inv.status.value,
        created_at=inv.created_at,
        paid_at=inv.paid_at,
    )


@router.post("/deposit", response_model=InvoiceStatusOut)
async def manual_deposit(body: DepositReq, user: CurrentUser, session: SessionDep):
    inv = Invoice(
        owner_id=user.id,
        provider=InvoiceProvider.cryptobot,
        provider_invoice_id=f"manual-{user.id}-{body.amount}",
        amount=body.amount,
        status=InvoiceStatus.pending,
    )
    session.add(inv)
    await session.commit()
    await session.refresh(inv)
    return InvoiceStatusOut(
        id=inv.id,
        amount=float(inv.amount),
        status=inv.status.value,
        created_at=inv.created_at,
        paid_at=inv.paid_at,
    )


@router.post("/withdraw")
async def withdraw(body: WithdrawReq, user: CurrentUser, session: SessionDep):
    if float(user.balance) < body.amount:
        raise HTTPException(400, "Недостаточно средств")
    user.balance = float(user.balance) - body.amount
    await session.commit()
    return {"ok": True, "new_balance": float(user.balance)}
