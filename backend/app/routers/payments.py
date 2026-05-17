from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from ..deps import SessionDep
from ..services_payments import (
    handle_invoice_expired,
    handle_invoice_paid,
    verify_webhook_signature,
    webhook_secret,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["payments"])


@router.post("/webhook/cryptobot")
async def cryptobot_webhook(request: Request, session: SessionDep):
    """Receive a Crypto Pay update.

    The Crypto Pay app posts JSON with ``update_type`` and ``payload``.
    We verify ``crypto-pay-api-signature`` against the bot token, then
    dispatch by ``update_type``. Response is always 200 (with an ``ok``
    bool) so Crypto Pay doesn't keep retrying on benign duplicates.

    H-1: the legacy USD ``Invoice`` ledger and its
    ``GET /api/payments/deposit`` / ``POST /api/payments/deposit`` /
    ``GET /api/payments/deposit/invoice/{id}`` /
    ``POST /api/payments/deposit/invoice`` endpoints were retired.
    The webhook URL stays at ``POST /api/payments/webhook/cryptobot``
    so existing CryptoBot configurations keep working.
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
