from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from ..config import settings
from ..cryptopay import CryptoPay, CryptoPayError
from ..deps import CurrentUser, SessionDep
from ..models import Invoice, InvoiceProvider, InvoiceStatus
from ..rate_limit import rate_limit
from ..schemas import DepositReq, InvoiceCreateReq, InvoiceOut, InvoiceStatusOut
from ..services import credit_invoice
from ..services_payments import (
    handle_invoice_expired,
    handle_invoice_paid,
    verify_webhook_signature,
    webhook_secret,
)

# Legacy USD-invoice creation. Keeping it ungated previously let any
# authenticated user spam thousands of pending ``Invoice`` rows; cap to
# a few per minute per user. The cap is intentionally generous because
# the surface is only kept for backward-compat with the old DepositPage.
_LIMIT_MANUAL_DEPOSIT = rate_limit("manual-deposit", limit=10, window=60)

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
        # V11-L-15 — structured-logging fields so the JSON-logger
        # downstream (Loki/Sentry) can pivot on event/user without
        # regexing the message body.
        logger.error(
            "CryptoBot error: %s",
            e,
            extra={
                "event": "cryptobot.legacy_create_invoice.failed",
                "user_id": user.id,
                "amount": float(body.amount),
            },
        )
        raise HTTPException(502, f"Ошибка CryptoBot: {e}")

    # V5-B-3 — same pay_url fallback chain as the wallet path. The
    # legacy Invoice model only persists ``provider_invoice_id`` (not
    # the URL), so if CryptoBot returns an invoice with no URL the
    # frontend has no fallback at all — the response below would set
    # ``pay_url=""`` and the deposit button would be inert. Fail loud
    # with 502 instead of silently handing the client a broken row.
    pay_url = (
        invoice.mini_app_invoice_url
        or invoice.bot_invoice_url
        or invoice.pay_url
        or invoice.web_app_invoice_url
        or ""
    )
    if not pay_url:
        logger.error(
            "CryptoBot create_invoice returned no pay_url for legacy USD invoice_id=%s",
            invoice.invoice_id,
            extra={
                "event": "cryptobot.legacy_create_invoice.empty_pay_url",
                "provider_invoice_id": str(invoice.invoice_id),
                "user_id": user.id,
            },
        )
        raise HTTPException(502, "CryptoBot не вернул ссылку для оплаты")

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
        pay_url=pay_url,
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
                # V5-B-2 follow-up — re-load the Invoice with
                # ``FOR UPDATE`` before crediting so this polling
                # fallback acquires locks in the same order as the
                # webhook path (``services_payments.handle_invoice_paid``):
                # Invoice -> User. Without this, the webhook's
                # Invoice lock and the poll path's User lock form a
                # cycle that Postgres resolves with a deadlock abort.
                #
                # ``populate_existing=True`` is required because
                # ``inv`` is already in the session's identity map
                # (the ``session.get(Invoice, invoice_id)`` above
                # loaded it). Without it, SQLAlchemy issues the
                # ``SELECT ... FOR UPDATE`` (acquiring the row lock)
                # but returns the cached instance with its pre-lock
                # column values, so ``locked.status`` would read the
                # stale ``pending`` even after a sibling webhook
                # just committed ``paid``. With the option set,
                # attribute values are refreshed from the result row
                # and the recheck below is the primary serialising
                # guard. The User-lock + status recheck inside
                # ``credit_invoice`` remains as defence-in-depth.
                locked = (
                    await session.execute(
                        select(Invoice)
                        .where(Invoice.id == inv.id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).scalar_one()
                if locked.status == InvoiceStatus.pending:
                    inv = await credit_invoice(session, locked)
                else:
                    inv = locked
        except CryptoPayError as e:
            logger.warning(
                "CryptoBot poll error: %s",
                e,
                extra={
                    "event": "cryptobot.legacy_poll.failed",
                    "invoice_id": inv.id,
                    "provider_invoice_id": inv.provider_invoice_id,
                },
            )

    return InvoiceStatusOut(
        id=inv.id,
        amount=float(inv.amount),
        status=inv.status.value,
        created_at=inv.created_at,
        paid_at=inv.paid_at,
    )


@router.post(
    "/deposit",
    response_model=InvoiceStatusOut,
    dependencies=[Depends(_LIMIT_MANUAL_DEPOSIT)],
)
async def manual_deposit(body: DepositReq, user: CurrentUser, session: SessionDep):
    # ``Invoice.provider_invoice_id`` is UNIQUE, so the suffix has to
    # be globally unique per row — a UUID is the cheapest way.
    inv = Invoice(
        owner_id=user.id,
        provider=InvoiceProvider.cryptobot,
        provider_invoice_id=f"manual-{user.id}-{body.amount}-{uuid4().hex}",
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

    # Fail closed: if the bot token is unconfigured we have no way to
    # verify the signature, so accepting the body would let an
    # unauthenticated caller credit any local invoice by id. 503 with a
    # neutral message lets Crypto Pay surface the misconfig in retries
    # without leaking that the token is empty.
    if not secret:
        logger.error(
            "CryptoBot webhook: token not configured — refusing",
            extra={"event": "cryptobot.webhook.token_missing"},
        )
        raise HTTPException(503, "Webhooks disabled (CryptoBot not configured)")

    if not verify_webhook_signature(secret, raw, signature):
        logger.warning(
            "CryptoBot webhook bad signature",
            extra={
                "event": "cryptobot.webhook.bad_signature",
                # Include the *presence* (boolean) rather than the
                # actual signature value so log records don't leak
                # the signature blob into Loki indexes.
                "signature_present": bool(signature),
            },
        )
        raise HTTPException(401, "Bad signature")

    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "Body must be JSON")

    # V5-B-8 — Crypto Pay's webhook envelope has ALWAYS used
    # ``update_type`` (per their public docs, `https://help.crypt.bot/
    # crypto-pay-api#webhooks`). The previous ``or body.get("type")``
    # fallback predated that and survived in the codebase as cargo;
    # it was never observed in a real Crypto Pay delivery and would
    # match unrelated payloads (e.g. a generic ``{"type": "..."}``
    # health-check ping from a scanner) and route them through the
    # invoice-paid handler. Drop the fallback so we only accept
    # genuinely-shaped payloads.
    update_type = body.get("update_type")
    payload = body.get("payload") or {}

    if update_type == "invoice_paid":
        # Crypto Pay sometimes posts ``status="expired"`` on the
        # ``invoice_paid`` channel too — route those through the
        # expired handler so we don't accidentally credit a dead row.
        if payload.get("status") == "expired":
            result = await handle_invoice_expired(session, payload)
        else:
            result = await handle_invoice_paid(session, payload)
        return {"ok": True, **result}

    if update_type == "invoice_expired":
        result = await handle_invoice_expired(session, payload)
        return {"ok": True, **result}

    logger.info(
        "CryptoBot webhook ignored update_type=%s",
        update_type,
        extra={
            "event": "cryptobot.webhook.ignored",
            "update_type": update_type or "unknown",
        },
    )
    return {"ok": True, "ignored": update_type or "unknown"}
