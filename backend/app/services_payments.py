"""CryptoBot wallet-deposit intake.

The webhook handler for ``invoice_paid`` / ``invoice_expired``:

* looks the row up by its ``provider_invoice_id`` in ``wallet_deposits``,
* marks it paid / expired,
* credits the user's per-currency balance via
  :func:`services_wallet.credit_deposit`,
* pushes a notification,
* never double-credits on retries (``SELECT ... FOR UPDATE`` lock + a
  status recheck after the lock returns).

H-1: the legacy USD ``Invoice`` ledger and its ``credit_invoice`` path
were retired together with the ``users.balance`` column. The webhook
now serves a single (multi-currency) ledger.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import crystalpay as crystalpay_client
from . import notifier
from .config import settings
from .crystalpay import (
    INVOICE_STATE_FAILED,
    INVOICE_STATE_PAID,
    INVOICE_STATE_UNAVAILABLE,
)
from .models import (
    WalletDeposit,
    WalletDepositStatus,
)
from .services_wallet import _build_expired_notification, credit_deposit

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


async def _find_wallet_deposit(
    session: AsyncSession, provider_invoice_id: str, *, lock: bool = False
) -> WalletDeposit | None:
    """Look up a ``WalletDeposit`` row by its CryptoBot id.

    when ``lock`` is true, the row is fetched with
    ``SELECT ... FOR UPDATE`` so two concurrent webhook deliveries
    serialise on the row instead of both reading ``pending`` and both
    crediting. The caller is expected to re-check ``status`` after the
    lock returns to detect the case where the other transaction
    already flipped the row to ``paid`` while we were blocked.
    """
    stmt = select(WalletDeposit).where(WalletDeposit.provider_invoice_id == provider_invoice_id)
    if lock:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
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

    wallet = await _find_wallet_deposit(session, provider_id, lock=True)
    if wallet is not None:
        # re-check status after acquiring the FOR UPDATE
        # lock: a sibling webhook delivery (CryptoBot retry / proxy
        # duplication) may have credited the deposit while we were
        # blocked on the row lock. If so, return idempotently
        # without crediting twice.
        if wallet.status == WalletDepositStatus.paid:
            return {"ok": True, "already_paid": True, "kind": "wallet"}
        await credit_deposit(session, wallet)
        return {"ok": True, "kind": "wallet"}

    logger.warning(
        "CryptoBot webhook for unknown invoice_id=%s",
        provider_id,
        # V11-L-15 — structured-logging fields so Loki/Sentry can
        # pivot on ``event`` + ``provider_invoice_id`` instead of
        # regexing the human-readable message.
        extra={
            "event": "cryptobot.webhook.unknown_invoice_paid",
            "provider_invoice_id": provider_id,
        },
    )
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

    wallet = await _find_wallet_deposit(session, provider_id, lock=True)
    if wallet is not None:
        # Terminal states are sticky — never flip ``paid`` back to
        # ``expired`` even if Crypto Pay sends a stale update; that
        # would silently de-credit the user. The ``lock=True`` above
        # closes the V5-B-1 follow-up gap: pre-fix, this branch
        # raced with ``handle_invoice_paid`` (which now takes the
        # row lock) so a stale ``expired`` delivery could clobber a
        # freshly-paid row to ``status=expired`` after the balance
        # had already been credited. With both webhook entry points
        # serialised on the row lock, the recheck below runs against
        # the locked, post-paid value and short-circuits cleanly.
        if wallet.status in (
            WalletDepositStatus.paid,
            WalletDepositStatus.expired,
            WalletDepositStatus.refunded,
        ):
            return {"ok": True, "already_terminal": True, "kind": "wallet"}
        wallet.status = WalletDepositStatus.expired
        # A9-M-2 — insert the notification atomically with the
        # status flip; dispatch after commit so a rolled-back txn
        # never leaks a "deposit expired" toast.
        entry = await _build_expired_notification(session, wallet)
        await session.commit()
        if entry is not None:
            notif, ws_payload = entry
            try:
                await notifier.dispatch_after_commit(session, notif, ws_payload)
            except Exception:
                logger.exception(
                    "handle_invoice_expired: post-commit dispatch failed for notif id=%s",
                    notif.id,
                    extra={
                        "event": "cryptobot.webhook.expired_dispatch.failed",
                        "notif_id": notif.id,
                    },
                )
        return {"ok": True, "kind": "wallet", "expired": True}

    logger.info(
        "CryptoBot webhook expire for unknown invoice_id=%s",
        provider_id,
        extra={
            "event": "cryptobot.webhook.unknown_invoice_expired",
            "provider_invoice_id": provider_id,
        },
    )
    return {"ok": False, "reason": "unknown invoice"}


def webhook_secret() -> str:
    """Secret used to verify Crypto Pay webhook signatures."""
    return settings.cryptobot_token or ""


# ── Crystalpay ────────────────────────────────────────────────


def crystalpay_webhook_secret() -> str:
    """Cashbox secret used to verify Crystalpay webhook signatures.

    Crystalpay's webhook is signed as ``sha1(f"{invoice_id}:{secret}")``
    where ``secret`` is the cashbox API secret. We re-use the same
    secret configured for the v3 API client.
    """
    return settings.crystalpay_secret or ""


def _crystalpay_provider_id(payload: dict[str, Any]) -> str | None:
    """Pluck the invoice id out of a Crystalpay webhook body.

    Crystalpay sends ``id`` as a string in the JSON envelope; older
    deliveries used ``invoice_id``. Accept either so a docs-version
    drift on the upstream side doesn't lose webhooks.
    """
    invoice_id = payload.get("id") or payload.get("invoice_id")
    if invoice_id is None:
        return None
    return str(invoice_id)


async def handle_crystalpay_invoice(
    session: AsyncSession, payload: dict[str, Any]
) -> dict[str, Any]:
    """Idempotently apply a Crystalpay webhook delivery.

    Crystalpay posts one envelope per state change with the invoice
    ``id`` and ``state``. We translate the upstream state into the
    same paid / expired transitions the CryptoBot path uses, with
    the same ``SELECT ... FOR UPDATE`` lock + status recheck against
    double credit / double expire.
    """
    provider_id = _crystalpay_provider_id(payload)
    if provider_id is None:
        return {"ok": False, "reason": "missing invoice id"}
    state = str(payload.get("state") or "").lower()

    wallet = await _find_wallet_deposit(session, provider_id, lock=True)
    if wallet is None:
        logger.warning(
            "Crystalpay webhook for unknown invoice id=%s",
            provider_id,
            extra={
                "event": "crystalpay.webhook.unknown_invoice",
                "provider_invoice_id": provider_id,
                "state": state,
            },
        )
        return {"ok": False, "reason": "unknown invoice"}

    if state == INVOICE_STATE_PAID:
        if wallet.status == WalletDepositStatus.paid:
            return {"ok": True, "already_paid": True, "kind": "wallet"}
        if wallet.status in (
            WalletDepositStatus.expired,
            WalletDepositStatus.refunded,
        ):
            # Crystalpay flipped the invoice to ``payed`` after we
            # had already terminal-stated the row (most likely an
            # out-of-order webhook delivery). Log it loudly but do
            # not credit — the user already saw the deposit close.
            logger.error(
                "Crystalpay paid webhook for non-pending deposit id=%s status=%s",
                wallet.id,
                wallet.status.value,
                extra={
                    "event": "crystalpay.webhook.paid_on_terminal",
                    "deposit_id": wallet.id,
                    "provider_invoice_id": provider_id,
                    "deposit_status": wallet.status.value,
                },
            )
            return {"ok": False, "reason": "deposit not pending"}
        await credit_deposit(session, wallet)
        return {"ok": True, "kind": "wallet"}

    if state in (INVOICE_STATE_UNAVAILABLE, INVOICE_STATE_FAILED):
        if wallet.status in (
            WalletDepositStatus.paid,
            WalletDepositStatus.expired,
            WalletDepositStatus.refunded,
        ):
            return {"ok": True, "already_terminal": True, "kind": "wallet"}
        wallet.status = WalletDepositStatus.expired
        entry = await _build_expired_notification(session, wallet)
        await session.commit()
        if entry is not None:
            notif, ws_payload = entry
            try:
                await notifier.dispatch_after_commit(session, notif, ws_payload)
            except Exception:
                logger.exception(
                    "handle_crystalpay_invoice: post-commit dispatch failed for notif id=%s",
                    notif.id,
                    extra={
                        "event": "crystalpay.webhook.expired_dispatch.failed",
                        "notif_id": notif.id,
                    },
                )
        return {"ok": True, "kind": "wallet", "expired": True}

    logger.info(
        "Crystalpay webhook ignored state=%s for id=%s",
        state or "unknown",
        provider_id,
        extra={
            "event": "crystalpay.webhook.ignored_state",
            "provider_invoice_id": provider_id,
            "state": state or "unknown",
        },
    )
    return {"ok": True, "ignored_state": state or "unknown"}


__all__ = [
    "crystalpay_webhook_secret",
    "handle_crystalpay_invoice",
    "handle_invoice_expired",
    "handle_invoice_paid",
    "verify_webhook_signature",
    "webhook_secret",
]


# Re-export crystalpay's signature helper so callers can ``from
# services_payments import verify_crystalpay_webhook_signature`` and
# stay decoupled from the client module's name.
verify_crystalpay_webhook_signature = crystalpay_client.verify_webhook_signature
