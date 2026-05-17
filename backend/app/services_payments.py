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

from .config import settings
from .models import WalletDeposit, WalletDepositStatus
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


async def _find_wallet_deposit(
    session: AsyncSession, provider_invoice_id: str, *, lock: bool = False
) -> WalletDeposit | None:
    """Look up a ``WalletDeposit`` row by its CryptoBot id.

    V5-B-1 — when ``lock`` is true, the row is fetched with
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
        # V5-B-1 — re-check status after acquiring the FOR UPDATE
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
        await session.commit()
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
