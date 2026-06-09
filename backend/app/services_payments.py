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
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
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
    WalletDepositProvider,
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
    session: AsyncSession,
    provider_invoice_id: str,
    *,
    provider: WalletDepositProvider,
    lock: bool = False,
) -> WalletDeposit | None:
    """Look up a ``WalletDeposit`` row by ``(provider, provider_invoice_id)``.

    Audit H-6 — pre-fix the lookup keyed only on
    ``provider_invoice_id`` and indexed it for FK-lookup speed but
    did NOT make the column unique across providers. CryptoBot and
    Crystalpay each maintain their own ``invoice_id`` namespace
    starting from ``1``, so a Crystalpay invoice with ``id=42`` and
    a CryptoBot invoice with ``invoice_id=42`` would collide on the
    lookup. The Crystalpay webhook handler could then load a
    CryptoBot row (or vice versa) and either credit the wrong user,
    flip the wrong row to ``expired``, or silently no-op (depending
    on which row was returned by ``scalar_one_or_none``).

    The fix narrows the lookup to ``(provider, provider_invoice_id)``
    so each provider's invoice id namespace is isolated. The
    ``provider`` parameter is required (no default) so a future
    caller can't reintroduce the collision by forgetting to pass it.

    When ``lock`` is true, the row is fetched with
    ``SELECT ... FOR UPDATE`` so two concurrent webhook deliveries
    from the SAME provider serialise on the row instead of both
    reading ``pending`` and both crediting. The caller is expected
    to re-check ``status`` after the lock returns to detect the
    case where the other transaction already flipped the row to
    ``paid`` while we were blocked.
    """
    stmt = select(WalletDeposit).where(
        WalletDeposit.provider == provider,
        WalletDeposit.provider_invoice_id == provider_invoice_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# Audit L-9 — tolerance for the upstream-vs-local amount equality
# check. Both CryptoBot and Crystalpay quote up to 8 fractional
# digits, so 1e-8 is one unit in the last decimal place. We keep
# the comparison inclusive to absorb rounding noise on the
# provider side without letting a partial payment slip through.
_AMOUNT_MISMATCH_TOLERANCE = Decimal("0.00000001")


def _parse_paid_amount(reported: Any) -> Decimal | None:
    """Best-effort parse of the webhook-reported ``paid`` amount.

    Crypto Pay sends strings, Crystalpay sends numbers. Returns
    ``None`` if the value is missing or unparseable so the
    downstream ``complete_deal_topup_payment`` falls back to the
    invoice's nominal ``amount``.
    """
    if reported is None:
        return None
    try:
        return Decimal(str(reported))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _amounts_match(reported: Any, expected: Any) -> bool:
    """Compare a webhook-reported amount against the deposit row.

    ``reported`` is whatever the provider sent in ``payload["amount"]``
    (string, int or float — Crypto Pay emits string, Crystalpay emits
    a number) and ``expected`` is ``wallet.amount`` (annotated
    ``Mapped[float]`` in the ORM but realised as ``Decimal`` at
    runtime — ``Numeric(28,8)``). Both sides are normalised through
    ``Decimal(str(...))`` so the comparison stays exact.

    Returns ``True`` if the reported amount is at least the expected
    amount minus :data:`_AMOUNT_MISMATCH_TOLERANCE`. Returns ``False``
    if parsing fails or the value is smaller — caller must not
    credit in that case.
    """
    if reported is None or expected is None:
        return False
    try:
        reported_d = Decimal(str(reported))
        expected_d = Decimal(str(expected))
    except (InvalidOperation, ValueError, TypeError):
        return False
    # ``>=`` (not ``==``) — overpayments by the user must not block
    # the credit, only underpayments must. ``- tolerance`` absorbs
    # last-decimal-place rounding noise on the provider side.
    return reported_d >= expected_d - _AMOUNT_MISMATCH_TOLERANCE


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

    # Audit H-6 — scope lookup to CryptoBot rows only; a Crystalpay
    # invoice with the same id must NOT be returned here.
    wallet = await _find_wallet_deposit(
        session, provider_id, provider=WalletDepositProvider.cryptobot, lock=True
    )
    if wallet is not None:
        # re-check status after acquiring the FOR UPDATE
        # lock: a sibling webhook delivery (CryptoBot retry / proxy
        # duplication) may have credited the deposit while we were
        # blocked on the row lock. If so, return idempotently
        # without crediting twice.
        if wallet.status == WalletDepositStatus.paid:
            return {"ok": True, "already_paid": True, "kind": "wallet"}
        if wallet.status == WalletDepositStatus.refunded:
            # A refunded deposit is an admin reversal of a previously
            # credited invoice. CryptoBot may still send a later paid
            # delivery with a fresh update id; treating that like a
            # missed webhook would silently undo the refund and credit
            # the user's balance again.
            logger.error(
                "CryptoBot paid webhook for refunded deposit id=%s",
                wallet.id,
                extra={
                    "event": "cryptobot.webhook.paid_on_refunded",
                    "deposit_id": wallet.id,
                    "provider_invoice_id": provider_id,
                },
            )
            return {"ok": False, "reason": "deposit not pending"}
        # Audit L-9 — defensive equality check between the reported
        # ``payload["amount"]`` and the deposit row's
        # ``wallet.amount``. We don't *trust* the provider to never
        # send "paid" on a partial payment, so an underpayment
        # detected here halts the credit, logs a structured warning
        # (so SRE can correlate via ``event`` + ``provider_invoice_id``),
        # and returns a sentinel reason so the webhook router can
        # echo it back / Sentry can fingerprint on the dict key.
        # The deposit row stays in ``pending`` so a follow-up
        # delivery (or a manual reconciliation) can still credit it
        # once the discrepancy is understood.
        reported = payload.get("amount")
        # P10 — ``deal_topup`` invoices accept ANY paid amount
        # (under-/overpayment is part of the spec) and the
        # settlement logic in ``complete_deal_topup_payment``
        # branches on ``paid - commission``. Skip the strict
        # equality check for those rows. ``wallet`` / ``trust``
        # purposes keep the existing defensive amount-mismatch
        # guard so legacy invoices can't be credited on a partial
        # provider-side payment.
        if wallet.purpose != "deal_topup" and not _amounts_match(reported, wallet.amount):
            logger.warning(
                "CryptoBot webhook amount mismatch invoice_id=%s reported=%s expected=%s",
                provider_id,
                reported,
                wallet.amount,
                extra={
                    "event": "cryptobot.webhook.amount_mismatch",
                    "provider_invoice_id": provider_id,
                    "deposit_id": wallet.id,
                    "reported_amount": str(reported),
                    "expected_amount": str(wallet.amount),
                },
            )
            return {"ok": False, "reason": "amount mismatch"}
        paid_decimal = _parse_paid_amount(reported)
        await credit_deposit(session, wallet, paid_amount=paid_decimal)
        return {"ok": True, "kind": wallet.purpose or "wallet"}

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

    # Audit H-6 — scope lookup to CryptoBot rows only.
    wallet = await _find_wallet_deposit(
        session, provider_id, provider=WalletDepositProvider.cryptobot, lock=True
    )
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
            except (TimeoutError, SQLAlchemyError, OSError, RuntimeError):
                # Audit (continuation) M-6 — narrowed from ``except
                # Exception``. See ``services_wallet.credit_deposit``
                # for the same allowlist rationale.
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

    # Audit H-6 — scope lookup to Crystalpay rows only; a CryptoBot
    # invoice with a colliding id must NOT be returned here.
    wallet = await _find_wallet_deposit(
        session, provider_id, provider=WalletDepositProvider.crystalpay, lock=True
    )
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
        # Audit L-9 — same defensive amount check as the CryptoBot
        # path. Crystalpay v3 sends the amount under ``amount`` in
        # the webhook envelope, sometimes as a string (when the
        # invoice currency is fiat) and sometimes as a number;
        # ``_amounts_match`` accepts both.
        reported = payload.get("amount")
        # P10 — see the matching note in ``handle_invoice_paid``.
        if wallet.purpose != "deal_topup" and not _amounts_match(reported, wallet.amount):
            logger.warning(
                "Crystalpay webhook amount mismatch id=%s reported=%s expected=%s",
                provider_id,
                reported,
                wallet.amount,
                extra={
                    "event": "crystalpay.webhook.amount_mismatch",
                    "provider_invoice_id": provider_id,
                    "deposit_id": wallet.id,
                    "reported_amount": str(reported),
                    "expected_amount": str(wallet.amount),
                },
            )
            return {"ok": False, "reason": "amount mismatch"}
        paid_decimal = _parse_paid_amount(reported)
        await credit_deposit(session, wallet, paid_amount=paid_decimal)
        return {"ok": True, "kind": wallet.purpose or "wallet"}

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
            except (TimeoutError, SQLAlchemyError, OSError, RuntimeError):
                # Audit (continuation) M-6 — see above.
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
