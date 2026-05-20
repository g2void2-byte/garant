from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from ..deps import SessionDep
from ..services_payments import (
    crystalpay_webhook_secret,
    handle_crystalpay_invoice,
    handle_invoice_expired,
    handle_invoice_paid,
    verify_crystalpay_webhook_signature,
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
    except ValueError as e:
        raise HTTPException(400, "Body must be JSON") from e

    # Crypto Pay's webhook envelope has ALWAYS used
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

    # M-14: a Crypto Pay delivery that doesn't match any handled
    # ``update_type`` is either (a) a benign new event type Crypto
    # Pay introduced — worth knowing about so we add a handler — or
    # (b) a stray scanner ping / mis-routed payload. Either case is
    # worth more than INFO so dashboards / log alerts can surface it.
    logger.warning(
        "CryptoBot webhook ignored update_type=%s",
        update_type,
        extra={
            "event": "cryptobot.webhook.ignored",
            "update_type": update_type or "unknown",
        },
    )
    return {"ok": True, "ignored": update_type or "unknown"}


@router.post("/webhook/crystalpay")
async def crystalpay_webhook(request: Request, session: SessionDep):
    """Receive a Crystalpay v3 webhook update.

    Crystalpay posts a JSON envelope containing the invoice ``id``,
    ``state`` and a ``signature`` field. The signature is
    ``sha1(f"{id}:{secret}")`` where ``secret`` is the cashbox API
    secret (the same secret used for the v3 API). We verify it with
    :func:`backend.app.crystalpay.verify_webhook_signature`, then
    dispatch on ``state`` via :func:`handle_crystalpay_invoice`.

    Response is always 200 (with an ``ok`` bool) for benign
    duplicates so Crystalpay doesn't keep retrying.
    """
    secret = crystalpay_webhook_secret()
    if not secret:
        logger.error(
            "Crystalpay webhook: secret not configured \u2014 refusing",
            extra={"event": "crystalpay.webhook.secret_missing"},
        )
        raise HTTPException(503, "Webhooks disabled (Crystalpay not configured)")

    try:
        body = await request.json()
    except ValueError as e:
        raise HTTPException(400, "Body must be JSON") from e
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object")

    invoice_id = body.get("id") or body.get("invoice_id")
    signature = body.get("signature")
    invoice_id_str = str(invoice_id) if invoice_id is not None else None
    signature_str = str(signature) if isinstance(signature, str) else None

    if not verify_crystalpay_webhook_signature(invoice_id_str or "", secret, signature_str):
        logger.warning(
            "Crystalpay webhook bad signature",
            extra={
                "event": "crystalpay.webhook.bad_signature",
                "signature_present": bool(signature_str),
                "invoice_id_present": bool(invoice_id_str),
            },
        )
        raise HTTPException(401, "Bad signature")

    result = await handle_crystalpay_invoice(session, body)
    return {"ok": True, **result}
