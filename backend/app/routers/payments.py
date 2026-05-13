from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from ..config import settings
from ..cryptopay import CryptoPay, CryptoPayError
from ..deps import CurrentUser, SessionDep
from ..models import Invoice, InvoiceProvider, InvoiceStatus
from ..schemas import DepositReq, InvoiceCreateReq, InvoiceOut, InvoiceStatusOut
from ..services import credit_invoice
from ..services_payments import (
    handle_invoice_paid,
    verify_webhook_signature,
    webhook_secret,
)

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
    body: InvoiceCreateReq,
    user: CurrentUser,
    session: SessionDep,
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
    """Polling fallback for legacy USD invoices.

    Webhook (``POST /api/payments/webhook/cryptobot``) is the primary
    path; this endpoint stays so the legacy DepositPage can still pull
    state directly if a webhook is missed.
    """
    inv = await session.get(Invoice, invoice_id)
    if not inv or inv.owner_id != user.id:
        raise HTTPException(404, "Инвойс не найден")

    if inv.status == InvoiceStatus.pending and settings.cryptobot_token:
        try:
            async with CryptoPay(
                settings.cryptobot_token, testnet=settings.cryptobot_testnet
            ) as crypto:
                checks = await crypto.get_invoices(invoice_ids=[int(inv.provider_invoice_id)])
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


@router.post("/webhook/cryptobot")
async def cryptobot_webhook(request: Request, session: SessionDep):
    """Receive a Crypto Pay update.

    The Crypto Pay app posts JSON with ``update_type`` and ``payload``.
    We verify ``crypto-pay-api-signature`` against the bot token, then
    dispatch by ``update_type``. Response is always 200 (with an ``ok``
    bool) so Crypto Pay doesn't keep retrying on benign duplicates.
    """
    raw = await request.body()
    signature = request.headers.get("crypto-pay-api-signature")
    secret = webhook_secret()

    if secret and not verify_webhook_signature(secret, raw, signature):
        # Soft-reject: log and 401 so Crypto Pay surfaces the misconfig.
        logger.warning("CryptoBot webhook bad signature")
        raise HTTPException(401, "Bad signature")

    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "Body must be JSON")

    update_type = body.get("update_type") or body.get("type")
    payload = body.get("payload") or {}

    if update_type == "invoice_paid":
        result = await handle_invoice_paid(session, payload)
        return {"ok": True, **result}

    logger.info("CryptoBot webhook ignored update_type=%s", update_type)
    return {"ok": True, "ignored": update_type or "unknown"}
