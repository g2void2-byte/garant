"""Unified CryptoBot payment intake.

Both the legacy USD ``Invoice`` table (``services.credit_invoice``) and the
multi-currency ``WalletDeposit`` table (``services_wallet.credit_deposit``)
ultimately want the same thing on a successful ``invoice_paid`` webhook:
* look the row up by its ``provider_invoice_id``,
* mark it paid,
* credit the user's balance,
* push a notification,
* never double-credit on retries.

This module is the single, idempotent entry point for that. It supports
both legacy and wallet rows so callers don't have to know which one a
particular ``invoice_id`` belongs to.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Invoice, InvoiceStatus, WalletDeposit, WalletDepositStatus
from .services import credit_invoice
from .services_wallet import credit_deposit

logger = logging.getLogger(__name__)


def verify_webhook_signature(secret: str, body: bytes, signature: str | None) -> bool:
    """Validate a Crypto Pay webhook signature.

    Crypto Pay signs the raw request body with HMAC-SHA256 keyed by the
    SHA-256 hash of the bot token. See
    https://help.send.tg/en/articles/10279948-crypto-pay-api#h_28aa6b8e30
    """
    if not signature or not secret:
        return False
    key = hashlib.sha256(secret.encode()).digest()
    expected = hmac.new(key, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _find_legacy_invoice(session: AsyncSession, provider_invoice_id: str) -> Invoice | None:
    result = await session.execute(
        select(Invoice).where(Invoice.provider_invoice_id == provider_invoice_id)
    )
    return result.scalar_one_or_none()


async def _find_wallet_deposit(
    session: AsyncSession, provider_invoice_id: str
) -> WalletDeposit | None:
    result = await session.execute(
        select(WalletDeposit).where(WalletDeposit.provider_invoice_id == provider_invoice_id)
    )
    return result.scalar_one_or_none()


async def handle_invoice_paid(session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    """Idempotently credit the user balance for a paid invoice.

    Accepts the ``payload`` shape Crypto Pay sends for ``invoice_paid``::

        {
          "invoice_id": 123456,
          "status": "paid",
          "amount": "1.5",
          "asset": "USDT",
          ...
        }

    Returns a small status dict so the webhook router can echo it back.
    """
    if payload.get("status") != "paid":
        return {"ok": False, "reason": "status is not paid"}

    invoice_id = payload.get("invoice_id")
    if invoice_id is None:
        return {"ok": False, "reason": "missing invoice_id"}
    provider_id = str(invoice_id)

    wallet = await _find_wallet_deposit(session, provider_id)
    if wallet is not None:
        if wallet.status == WalletDepositStatus.paid:
            return {"ok": True, "already_paid": True, "kind": "wallet"}
        await credit_deposit(session, wallet)
        return {"ok": True, "kind": "wallet"}

    legacy = await _find_legacy_invoice(session, provider_id)
    if legacy is not None:
        if legacy.status == InvoiceStatus.paid:
            return {"ok": True, "already_paid": True, "kind": "legacy"}
        await credit_invoice(session, legacy)
        return {"ok": True, "kind": "legacy"}

    logger.warning("CryptoBot webhook for unknown invoice_id=%s", provider_id)
    return {"ok": False, "reason": "unknown invoice"}


async def handle_invoice_expired(session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    """I-3 — terminal-state a pending invoice the user never paid.

    Crypto Pay emits ``update_type=invoice_expired`` (and sometimes
    ``invoice_paid`` with ``status="expired"`` mid-funnel) when an
    invoice ages past its ``allow_anonymous`` window without payment.
    Pre-fix we ignored that and the row sat in ``pending`` until the
    M-6 sweep eventually closed it. Handling the webhook directly is
    cheaper and faster — the moment Crypto Pay decides the invoice is
    dead we mirror that state locally, so the user-facing list and
    the admin queue stop showing the row immediately.
    """
    invoice_id = payload.get("invoice_id")
    if invoice_id is None:
        return {"ok": False, "reason": "missing invoice_id"}
    provider_id = str(invoice_id)

    wallet = await _find_wallet_deposit(session, provider_id)
    if wallet is not None:
        # Terminal states are sticky — never flip ``paid`` back to
        # ``expired`` even if Crypto Pay sends a stale update; that
        # would silently de-credit the user.
        if wallet.status in (
            WalletDepositStatus.paid,
            WalletDepositStatus.expired,
            WalletDepositStatus.refunded,
        ):
            return {"ok": True, "already_terminal": True, "kind": "wallet"}
        wallet.status = WalletDepositStatus.expired
        await session.commit()
        return {"ok": True, "kind": "wallet", "expired": True}

    legacy = await _find_legacy_invoice(session, provider_id)
    if legacy is not None:
        if legacy.status in (InvoiceStatus.paid, InvoiceStatus.expired):
            return {"ok": True, "already_terminal": True, "kind": "legacy"}
        legacy.status = InvoiceStatus.expired
        await session.commit()
        return {"ok": True, "kind": "legacy", "expired": True}

    logger.info("CryptoBot webhook expire for unknown invoice_id=%s", provider_id)
    return {"ok": False, "reason": "unknown invoice"}


def webhook_secret() -> str:
    """Secret used to verify Crypto Pay webhook signatures."""
    return settings.cryptobot_token or ""
