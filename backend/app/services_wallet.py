"""Business logic for the multi-currency wallet.

Funds split between ``UserBalance.amount`` (spendable) and
``UserBalance.locked`` (held while a withdrawal is awaiting admin
review or during the cool-down window).
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from . import notifier
from .config import settings
from .cryptopay import CryptoPay, CryptoPayError
from .crystalpay import (
    INVOICE_STATE_FAILED,
    INVOICE_STATE_PAID,
    INVOICE_STATE_UNAVAILABLE,
    Crystalpay,
    CrystalpayError,
)
from .models import (
    AppSettings,
    Currency,
    Notification,
    NotificationType,
    User,
    UserBalance,
    WalletDeposit,
    WalletDepositProvider,
    WalletDepositStatus,
    WalletWithdrawal,
    WalletWithdrawStatus,
)
from .time_utils import utcnow

logger = logging.getLogger(__name__)


async def get_currency_by_code(session: AsyncSession, code: str) -> Currency:
    result = await session.execute(
        select(Currency).where(Currency.code == code.upper(), Currency.is_active.is_(True))
    )
    cur = result.scalar_one_or_none()
    if cur is None:
        raise HTTPException(404, f"Валюта {code} не поддерживается")
    return cur


async def get_or_create_balance(
    session: AsyncSession, user_id: int, currency_id: int
) -> UserBalance:
    """Return (or create) the user/currency balance row.

    V11-L-20 — pre-fix the missing-row branch did a naked
    ``session.add()`` which, under two concurrent first-touch
    requests for the same (user_id, currency_id) pair, blew up on
    the unique constraint of the loser. We now use
    ``INSERT ... ON CONFLICT DO NOTHING`` so the loser commits a
    no-op and re-SELECTs whichever row landed first. The
    ``flush()`` after the INSERT guarantees the row is visible to
    the follow-up SELECT inside the same transaction.

    6.3 — **Commit contract**: this helper does NOT call
    ``session.commit()``. The caller owns the transaction boundary;
    the upsert + select land in the caller's open transaction and
    are only durable when the caller commits. This is intentional
    so handlers can compose the balance read with subsequent writes
    (e.g. ``UserBalance.amount += delta``) atomically, but every
    caller MUST commit before returning a response — leaving the
    transaction open here would leak the row write on the next
    rollback boundary. The same contract applies to
    :func:`lock_user_balance` below.
    """
    result = await session.execute(
        select(UserBalance).where(
            UserBalance.user_id == user_id, UserBalance.currency_id == currency_id
        )
    )
    bal = result.scalar_one_or_none()
    if bal is not None:
        return bal
    await session.execute(
        pg_insert(UserBalance)
        .values(user_id=user_id, currency_id=currency_id, amount=0, locked=0)
        .on_conflict_do_nothing(index_elements=["user_id", "currency_id"])
    )
    await session.flush()
    bal = (
        await session.execute(
            select(UserBalance).where(
                UserBalance.user_id == user_id,
                UserBalance.currency_id == currency_id,
            )
        )
    ).scalar_one()
    return bal


async def lock_user_balance(session: AsyncSession, user_id: int, currency_id: int) -> UserBalance:
    """Return the user's balance row with a ``FOR UPDATE`` row lock held.

    Used by money-moving flows (withdrawal, deal creation) where two
    concurrent requests must not both pass an ``amount >= price``
    check.

    V11-L-20 — pre-fix the cold-path "row doesn't exist yet" branch
    did a naked ``session.add()`` which races identically to
    :func:`get_or_create_balance`. We now upsert with
    ``ON CONFLICT DO NOTHING`` and then ``SELECT ... FOR UPDATE``
    once we know the row exists. The lock acquired by the follow-up
    SELECT is the same one production callers rely on; the INSERT
    itself implicitly row-locks the newly created row, so even if
    the cold path takes it the contract holds.

    6.3 — **Commit contract**: this helper does NOT call
    ``session.commit()``. The ``FOR UPDATE`` row lock is held
    *until the caller commits or rolls back* — that is the entire
    point: the lock protects the caller's subsequent writes from
    a concurrent reader passing the same balance check. If the
    caller forgets to commit, the lock will be released by the
    session's auto-rollback at scope exit, but any balance write
    the caller made in between will also be discarded. Callers
    must therefore always commit on the success path and let the
    session context manager rollback on errors.
    """
    bal = (
        await session.execute(
            select(UserBalance)
            .where(
                UserBalance.user_id == user_id,
                UserBalance.currency_id == currency_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if bal is not None:
        return bal
    await session.execute(
        pg_insert(UserBalance)
        .values(user_id=user_id, currency_id=currency_id, amount=0, locked=0)
        .on_conflict_do_nothing(index_elements=["user_id", "currency_id"])
    )
    await session.flush()
    bal = (
        await session.execute(
            select(UserBalance)
            .where(
                UserBalance.user_id == user_id,
                UserBalance.currency_id == currency_id,
            )
            .with_for_update()
        )
    ).scalar_one()
    return bal


async def list_balances(
    session: AsyncSession, user_id: int
) -> list[tuple[Currency, UserBalance | None]]:
    """Return every active currency with the user's balance row (or None)."""
    currencies = (
        (
            await session.execute(
                select(Currency).where(Currency.is_active.is_(True)).order_by(Currency.sort_order)
            )
        )
        .scalars()
        .all()
    )
    balances = (
        (await session.execute(select(UserBalance).where(UserBalance.user_id == user_id)))
        .scalars()
        .all()
    )
    by_currency = {b.currency_id: b for b in balances}
    return [(c, by_currency.get(c.id)) for c in currencies]


# ── Deposits ───────────────────────────────────────────


async def create_deposit_invoice(
    session: AsyncSession,
    user: User,
    currency_code: str,
    amount: float,
    purpose: str = "wallet",
    provider: str = "cryptobot",
) -> WalletDeposit:
    """Create a wallet-deposit invoice on the configured ``provider``.

    Routes to :func:`_create_cryptobot_deposit` (default) or
    :func:`_create_crystalpay_deposit` based on the ``provider`` arg.
    The upstream invoice's lifetime is pinned to
    ``settings.wallet_deposit_expiry_seconds`` so all three sides —
    the local ``WalletDeposit`` row, the upstream provider invoice,
    and the background sweep — agree on the terminal moment.
    """
    currency = await get_currency_by_code(session, currency_code)
    if amount < float(currency.min_deposit):
        raise HTTPException(
            400, f"Минимальная сумма пополнения: {currency.min_deposit} {currency.code}"
        )
    # ``purpose`` is validated upstream by
    # ``WalletDepositCreateReq.purpose`` (a ``Literal["wallet", "trust"]``);
    # we still belt-and-suspenders here so non-HTTP callers (admin
    # tooling, tests) can't smuggle an invalid value through the
    # service layer.
    if purpose not in ("wallet", "trust"):
        raise HTTPException(400, f"Неизвестный тип депозита: {purpose}")

    if provider == "crystalpay":
        return await _create_crystalpay_deposit(session, user, currency, amount, purpose)
    if provider == "cryptobot":
        return await _create_cryptobot_deposit(session, user, currency, amount, purpose)
    raise HTTPException(400, f"Неизвестный провайдер: {provider}")


async def _create_cryptobot_deposit(
    session: AsyncSession,
    user: User,
    currency: Currency,
    amount: float,
    purpose: str,
) -> WalletDeposit:
    if not is_cryptopay_configured():
        raise HTTPException(502, "CryptoBot не настроен")

    expiry_seconds = int(settings.wallet_deposit_expiry_seconds)
    try:
        async with CryptoPay(
            settings.cryptobot_token, testnet=settings.cryptobot_testnet
        ) as crypto:
            invoice = await crypto.create_invoice(
                asset=currency.code,
                amount=amount,
                expires_in=expiry_seconds if expiry_seconds > 0 else None,
            )
    except CryptoPayError as e:
        # V11-L-15 — ``extra={}`` puts the user/currency/amount onto the
        # JSON log record as structured fields so Loki/Sentry queries
        # can pivot by them without regexing the message body.
        logger.error(
            "CryptoBot invoice error: %s",
            e,
            extra={
                "event": "cryptobot.create_invoice.failed",
                "user_id": user.id,
                "currency": currency.code,
                "amount": amount,
            },
        )
        raise HTTPException(502, f"Ошибка CryptoBot: {e}")

    # CryptoBot normally returns at least one non-empty URL,
    # but the API contract is "one of these four MAY be set" rather
    # than "exactly one is guaranteed". If they ever return all four
    # blank (e.g. a misconfigured asset on their side, or an API
    # version drift), the previous fallback chain quietly stored ``""``
    # and the frontend rendered a deposit card with a dead button —
    # the user paid via a different invoice and we eventually got a
    # webhook anyway, but the UX was broken. Fail loudly here so the
    # caller sees 502 instead of a half-broken deposit row in the DB.
    pay_url = (
        invoice.mini_app_invoice_url
        or invoice.bot_invoice_url
        or invoice.pay_url
        or invoice.web_app_invoice_url
        or ""
    )
    if not pay_url:
        logger.error(
            "CryptoBot create_invoice returned no pay_url for invoice_id=%s asset=%s",
            invoice.invoice_id,
            currency.code,
            extra={
                "event": "cryptobot.create_invoice.empty_pay_url",
                "provider_invoice_id": str(invoice.invoice_id),
                "user_id": user.id,
                "currency": currency.code,
            },
        )
        raise HTTPException(502, "CryptoBot не вернул ссылку для оплаты")
    deposit = WalletDeposit(
        user_id=user.id,
        currency_id=currency.id,
        amount=amount,
        provider=WalletDepositProvider.cryptobot,
        provider_invoice_id=str(invoice.invoice_id),
        pay_url=pay_url,
        status=WalletDepositStatus.pending,
        purpose=purpose,
    )
    session.add(deposit)
    await session.commit()
    return deposit


async def _create_crystalpay_deposit(
    session: AsyncSession,
    user: User,
    currency: Currency,
    amount: float,
    purpose: str,
) -> WalletDeposit:
    if not settings.crystalpay_login or not settings.crystalpay_secret:
        raise HTTPException(502, "Crystalpay не настроен")

    # Crystalpay v3 takes ``lifetime`` in **minutes**; round up so we
    # don't accidentally truncate a sub-minute window to zero.
    expiry_seconds = int(settings.wallet_deposit_expiry_seconds)
    if expiry_seconds <= 0:
        lifetime_minutes = 30
    else:
        lifetime_minutes = max(1, (expiry_seconds + 59) // 60)

    try:
        async with Crystalpay(settings.crystalpay_login, settings.crystalpay_secret) as cp:
            invoice = await cp.create_invoice(
                amount=amount,
                currency=currency.code,
                lifetime=lifetime_minutes,
                description=f"Garant wallet top-up for user #{user.id}",
                extra=f"user:{user.id}",
            )
    except CrystalpayError as e:
        logger.error(
            "Crystalpay invoice error: %s",
            e,
            extra={
                "event": "crystalpay.create_invoice.failed",
                "user_id": user.id,
                "currency": currency.code,
                "amount": amount,
            },
        )
        raise HTTPException(502, f"Ошибка Crystalpay: {e}")

    if not invoice.id or not invoice.url:
        logger.error(
            "Crystalpay create_invoice returned no id/url",
            extra={
                "event": "crystalpay.create_invoice.empty",
                "provider_invoice_id": str(invoice.id),
                "user_id": user.id,
                "currency": currency.code,
            },
        )
        raise HTTPException(502, "Crystalpay не вернул ссылку для оплаты")

    deposit = WalletDeposit(
        user_id=user.id,
        currency_id=currency.id,
        amount=amount,
        provider=WalletDepositProvider.crystalpay,
        provider_invoice_id=invoice.id,
        pay_url=invoice.url,
        status=WalletDepositStatus.pending,
        purpose=purpose,
    )
    session.add(deposit)
    await session.commit()
    return deposit


async def credit_deposit(session: AsyncSession, deposit: WalletDeposit) -> WalletDeposit:
    """Mark a deposit ``paid`` and credit the user balance. Idempotent.

    Branches on ``deposit.purpose``:

    * ``"wallet"`` (default) — increment ``UserBalance.amount`` for the
      deposit's currency, exactly like the legacy single-purpose flow.
    * ``"trust"`` — increment ``User.trust_deposit_balance`` instead.
      No per-currency split (the trust balance is a single scalar by
      design); the deposit's ``amount`` is added directly. There is
      *no* spend / withdraw path for this balance — the only readers
      are the public ``deposit`` field on ``UserOut`` / ``UserPublicOut``
      and the admin panel.

    Lock order for the trust branch is ``WalletDeposit → User`` (the
    deposit row is already locked by the caller — webhook /
    ``poll_deposit_status`` — and we take ``FOR UPDATE`` on the
    ``users`` row here). The wallet branch keeps its existing
    ``WalletDeposit → UserBalance`` order. Both pairs share their
    first link, and the second links are on disjoint tables, so a
    cross-branch deadlock is impossible.
    """
    if deposit.status == WalletDepositStatus.paid:
        return deposit

    purpose = deposit.purpose or "wallet"

    if purpose == "trust":
        # ``populate_existing`` reloads the row's columns from the
        # locking SELECT result even when the User is already in the
        # identity map (``deps.get_current_user`` etc. routinely warm
        # the cache). Without it we'd hold the row lock but read a
        # stale ``trust_deposit_balance`` and clobber a concurrent
        # webhook's increment.
        user_row = (
            await session.execute(
                select(User)
                .where(User.id == deposit.user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        await session.refresh(deposit, attribute_names=["status", "paid_at"])
        if deposit.status == WalletDepositStatus.paid:
            return deposit
        # See M5 in services_deals._debit for why this stays Decimal
        # end-to-end instead of round-tripping through ``float``.
        user_row.trust_deposit_balance = Decimal(str(user_row.trust_deposit_balance)) + Decimal(
            str(deposit.amount)
        )
        deposit.status = WalletDepositStatus.paid
        deposit.paid_at = utcnow()
    else:
        # take a FOR UPDATE lock on the user's balance row before
        # mutating it. Two concurrent webhook deliveries that race past
        # the deposit-row lock (or a webhook racing with the
        # ``poll_deposit_status`` polling fallback in services_wallet)
        # must serialise their balance writes here, otherwise the second
        # transaction's RMW can clobber the first transaction's
        # increment. ``lock_user_balance`` mirrors what ``create_withdrawal``
        # and the deal-creation ``_debit`` path already use.
        bal = await lock_user_balance(session, deposit.user_id, deposit.currency_id)

        # Re-read the deposit's status under the balance lock as
        # belt-and-suspenders behind the outer FOR UPDATE lock both
        # entry points now take on the deposit row before calling us:
        # the webhook path locks via ``_find_wallet_deposit(lock=True)``
        # in ``services_payments.handle_invoice_paid``, and the polling
        # path locks via ``select(...).with_for_update()
        # .execution_options(populate_existing=True)`` in
        # ``poll_deposit_status``. Those outer locks are the primary
        # serialising guard; this refresh+recheck just narrows the
        # window if a future caller forgets to acquire the deposit-row
        # lock first.
        await session.refresh(deposit, attribute_names=["status", "paid_at"])
        if deposit.status == WalletDepositStatus.paid:
            return deposit
        # See M5 in services_deals._debit for why this stays Decimal end-
        # to-end instead of round-tripping through ``float``.
        bal.amount = Decimal(str(bal.amount)) + Decimal(str(deposit.amount))
        deposit.status = WalletDepositStatus.paid
        deposit.paid_at = utcnow()

    # A9-M-2 — split-API: insert the notification row atomically with
    # the balance credit + deposit-status flip, dispatch WS/DM after
    # commit so a rolled-back transaction never leaks a "deposit
    # credited" toast to the user.
    currency = await session.get(Currency, deposit.currency_id)
    pending: tuple[Notification, dict[str, Any] | None] | None = None
    if currency:
        pending = await notifier.insert(
            session,
            deposit.user_id,
            NotificationType.deposits,
            "Пополнение зачислено",
            f"+{deposit.amount} {currency.code} зачислены на ваш баланс",
            {"deposit_id": deposit.id, "currency": currency.code},
        )

    await session.commit()

    if pending is not None:
        notif, ws_payload = pending
        try:
            await notifier.dispatch_after_commit(session, notif, ws_payload)
        except Exception:
            logger.exception(
                "credit_deposit: post-commit dispatch failed for notif id=%s",
                notif.id,
                extra={"event": "credit_deposit.dispatch.failed", "notif_id": notif.id},
            )

    return deposit


async def _build_expired_notification(
    session: AsyncSession, deposit: WalletDeposit
) -> tuple[Notification, dict[str, Any] | None] | None:
    """Insert (without commit) a ``deposits`` notification for an expired deposit.

    Returns the ``(notif, ws_payload)`` tuple to pass into
    :func:`notifier.dispatch_after_commit` after the caller commits.
    Returns ``None`` if the deposit's currency can't be resolved (the
    notification body would be useless without it).
    """
    currency = await session.get(Currency, deposit.currency_id)
    if currency is None:
        return None
    return await notifier.insert(
        session,
        deposit.user_id,
        NotificationType.deposits,
        "Срок депозита истёк",
        f"Счёт на {deposit.amount} {currency.code} истёк без оплаты. "
        "Создайте новый, если хотите пополнить баланс.",
        {"deposit_id": deposit.id, "currency": currency.code},
    )


async def sweep_expired_deposits(session: AsyncSession) -> int:
    """Mark stale ``pending`` deposits as ``expired``.

    M-6 — pre-fix, a ``WalletDeposit(status=pending)`` row created when
    the user clicked "deposit" but never paid sat in the admin queue
    forever. CryptoBot stops issuing webhooks for the invoice once it
    has expired on their side, so the row had no independent path to
    a terminal state. This sweep closes the loop: every
    ``wallet_deposit_sweep_seconds`` the loop in
    :mod:`backend.app.main` runs us and we flip any
    ``pending`` row older than ``wallet_deposit_expiry_seconds`` to
    ``expired``. No balance is credited; the user can always create
    a fresh deposit if they actually wanted to pay.

    A ``deposits``-bucket notification + DM is inserted atomically
    with each flip and dispatched after the row-level commit so the
    user actually finds out the invoice they walked away from is
    closed (pre-fix the sweep ran silently and the deposit just
    disappeared from the "pending" tab).

    Uses ``with_for_update(skip_locked=True)`` so a concurrent sweep
    in a sibling worker doesn't double-flip rows. Returns the number
    of rows touched so the caller can log it.
    """
    expiry_seconds = int(settings.wallet_deposit_expiry_seconds)
    if expiry_seconds <= 0:
        return 0

    cutoff = utcnow() - timedelta(seconds=expiry_seconds)

    rows = (
        (
            await session.execute(
                select(WalletDeposit)
                .where(
                    WalletDeposit.status == WalletDepositStatus.pending,
                    WalletDeposit.created_at <= cutoff,
                )
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )

    if not rows:
        return 0

    pending_dispatch: list[tuple[Notification, dict[str, Any] | None]] = []
    for row in rows:
        row.status = WalletDepositStatus.expired
        # A9-M-2 — insert the notification atomically with the
        # status flip; dispatch after commit so a rolled-back txn
        # never leaks a "deposit expired" toast.
        entry = await _build_expired_notification(session, row)
        if entry is not None:
            pending_dispatch.append(entry)

    await session.commit()

    for notif, ws_payload in pending_dispatch:
        try:
            await notifier.dispatch_after_commit(session, notif, ws_payload)
        except Exception:
            logger.exception(
                "sweep_expired_deposits: post-commit dispatch failed for notif id=%s",
                notif.id,
                extra={
                    "event": "sweep_expired_deposits.dispatch.failed",
                    "notif_id": notif.id,
                },
            )

    return len(rows)


async def poll_deposit_status(session: AsyncSession, deposit: WalletDeposit) -> WalletDeposit:
    """Refresh a pending deposit's status from the upstream provider. Idempotent.

    Dispatches to the per-provider helper based on ``deposit.provider``
    so the wallet poller can survive a mix of CryptoBot + Crystalpay
    rows in the same TMA session (each provider has its own ID space
    and on-the-wire ``status`` vocabulary).
    """
    if deposit.status != WalletDepositStatus.pending:
        return deposit
    if deposit.provider == WalletDepositProvider.crystalpay:
        return await _poll_crystalpay_deposit(session, deposit)
    return await _poll_cryptobot_deposit(session, deposit)


async def _poll_cryptobot_deposit(session: AsyncSession, deposit: WalletDeposit) -> WalletDeposit:
    if not settings.cryptobot_token:
        return deposit
    try:
        async with CryptoPay(
            settings.cryptobot_token, testnet=settings.cryptobot_testnet
        ) as crypto:
            rows = await crypto.get_invoices(invoice_ids=[int(deposit.provider_invoice_id)])
    except CryptoPayError as e:
        logger.warning(
            "CryptoBot poll error: %s",
            e,
            extra={
                "event": "cryptobot.poll_deposit.failed",
                "deposit_id": deposit.id,
                "provider_invoice_id": deposit.provider_invoice_id,
            },
        )
        return deposit

    if not rows:
        return deposit
    row = rows[0]
    if row.status == "paid":
        # re-load the deposit with ``FOR UPDATE``
        # before crediting so this polling-fallback path acquires
        # locks in the same order as the webhook
        # (``services_payments.handle_invoice_paid``):
        # WalletDeposit -> UserBalance. Without this, the webhook's
        # WalletDeposit lock and the poll path's UserBalance lock
        # form a cycle that Postgres resolves with a deadlock abort
        # for one of the transactions.
        #
        # ``populate_existing=True`` is required because ``deposit``
        # is already in the session's identity map (the caller
        # loaded it before calling us). Without it, SQLAlchemy
        # issues the ``SELECT ... FOR UPDATE`` (acquiring the row
        # lock) but returns the cached instance with its pre-lock
        # column values, so ``locked.status`` would read the stale
        # ``pending`` even after a sibling webhook just committed
        # ``paid``. With the option set, attribute values are
        # refreshed from the result row and the recheck below is
        # the primary serialising guard.
        return await _lock_and_credit_deposit(session, deposit)
    if row.status == "expired":
        return await _lock_and_expire_deposit(session, deposit)
    return deposit


async def _poll_crystalpay_deposit(session: AsyncSession, deposit: WalletDeposit) -> WalletDeposit:
    if not settings.crystalpay_login or not settings.crystalpay_secret:
        return deposit
    try:
        async with Crystalpay(settings.crystalpay_login, settings.crystalpay_secret) as cp:
            invoice = await cp.get_invoice(deposit.provider_invoice_id)
    except CrystalpayError as e:
        logger.warning(
            "Crystalpay poll error: %s",
            e,
            extra={
                "event": "crystalpay.poll_deposit.failed",
                "deposit_id": deposit.id,
                "provider_invoice_id": deposit.provider_invoice_id,
            },
        )
        return deposit

    if invoice.state == INVOICE_STATE_PAID:
        return await _lock_and_credit_deposit(session, deposit)
    if invoice.state in (INVOICE_STATE_UNAVAILABLE, INVOICE_STATE_FAILED):
        return await _lock_and_expire_deposit(session, deposit)
    return deposit


async def _lock_and_credit_deposit(session: AsyncSession, deposit: WalletDeposit) -> WalletDeposit:
    locked = (
        await session.execute(
            select(WalletDeposit)
            .where(WalletDeposit.id == deposit.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    if locked.status != WalletDepositStatus.pending:
        return locked
    return await credit_deposit(session, locked)


async def _lock_and_expire_deposit(session: AsyncSession, deposit: WalletDeposit) -> WalletDeposit:
    """Lock+flip a pending deposit to ``expired``, then notify the user.

    Same lock-order rationale as :func:`_lock_and_credit_deposit`:
    serialise with any concurrent webhook delivery on the same row
    and re-check ``status`` so we never clobber a freshly-paid
    deposit back to ``expired``. ``populate_existing=True`` for the
    same identity-map reason documented in the ``paid`` branch.
    """
    locked = (
        await session.execute(
            select(WalletDeposit)
            .where(WalletDeposit.id == deposit.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    if locked.status != WalletDepositStatus.pending:
        return locked
    locked.status = WalletDepositStatus.expired
    entry = await _build_expired_notification(session, locked)
    await session.commit()
    if entry is not None:
        notif, ws_payload = entry
        try:
            await notifier.dispatch_after_commit(session, notif, ws_payload)
        except Exception:
            logger.exception(
                "poll_deposit_status: post-commit dispatch failed for notif id=%s",
                notif.id,
                extra={
                    "event": "poll_deposit_status.dispatch.failed",
                    "notif_id": notif.id,
                },
            )
    return locked


# ── Withdrawals ────────────────────────────────────────


async def _auto_withdraw_enabled(session: AsyncSession) -> bool:
    row = (
        await session.execute(select(AppSettings).order_by(AppSettings.id).limit(1))
    ).scalar_one_or_none()
    return bool(row and row.auto_withdraw_enabled)


def is_cryptopay_configured(token: str | None = None) -> bool:
    """Return True iff a real (non-placeholder) CryptoBot token is configured.

    7.2 — the placeholder check is a heuristic, not a hard guarantee:
    we treat any token that ``startswith("000")`` as the well-known
    docker-compose default (``CRYPTOBOT_TOKEN=000000:FAKE``) so that
    dev/CI environments don't accidentally fire a network call to the
    real CryptoBot API on every withdrawal/transfer. A real CryptoBot
    token starts with the app id (numeric, currently 4–6 digits)
    followed by ``:`` — a real token whose app id starts with ``000``
    is theoretically possible but extremely unlikely in practice. If
    the upstream switches to longer / non-numeric prefixes (or if we
    want to harden this further), swap the heuristic for a length /
    prefix-and-format check.

    ``token`` defaults to ``settings.cryptobot_token`` so callers can
    use the no-arg form, but admin/system endpoints that pre-resolve
    the token (or test fixtures that inject an override) can pass it
    explicitly to avoid a second module-attribute lookup.
    """
    if token is None:
        token = settings.cryptobot_token or ""
    return bool(token) and not token.startswith("000")


# Internal alias kept for the historical name; new callers should use
# the public ``is_cryptopay_configured`` above.
_cryptopay_configured = is_cryptopay_configured


async def create_withdrawal(
    session: AsyncSession, user: User, currency_code: str, amount: float, address: str
) -> WalletWithdrawal:
    currency = await get_currency_by_code(session, currency_code)
    if amount < float(currency.min_withdraw):
        raise HTTPException(
            400, f"Минимальная сумма вывода: {currency.min_withdraw} {currency.code}"
        )

    # per-currency anchored regex check. Anchored on both
    # ends because ``re.fullmatch`` already requires the whole string
    # to match; the ``^...$`` markers in the seed are defensive against
    # someone swapping ``fullmatch`` for ``search`` later. An empty
    # ``address_regex`` means "validation deliberately disabled for
    # this currency" (e.g. a future asset added before its regex is
    # known) — fall through and let CryptoBot's ``transfer`` validate
    # at payout time, same as before this audit item. We do NOT
    # ``re.compile`` here because the regex column rarely changes and
    # Python's regex cache caps at 512 patterns — well above the ~10
    # currencies we ship.
    if currency.address_regex and not re.fullmatch(currency.address_regex, address):
        raise HTTPException(400, f"Неверный формат адреса для {currency.code} ({currency.network})")

    # Row-lock the balance: two concurrent withdrawals must not both
    # pass the ``amount >= price`` check on the same balance.
    bal = await lock_user_balance(session, user.id, currency.id)
    amount_d = Decimal(str(amount))
    current = Decimal(str(bal.amount))
    if current < amount_d:
        raise HTTPException(400, "Недостаточно средств")

    # Decimal end-to-end: ``Numeric(28,8)`` accepts Decimal natively;
    # round-tripping through ``float`` (the previous M5 buggy path)
    # drops the last 2-3 significant digits at the 10^10 scale that
    # USDT can hit.
    bal.amount = current - amount_d
    bal.locked = Decimal(str(bal.locked)) + amount_d

    withdrawal = WalletWithdrawal(
        user_id=user.id,
        currency_id=currency.id,
        amount=amount,
        address=address,
        status=WalletWithdrawStatus.pending,
    )
    session.add(withdrawal)
    await session.commit()

    # If auto-mode is on and CryptoBot is configured, fire the transfer
    # immediately so the user doesn't wait on an admin. Failures here
    # leave the withdrawal in ``pending`` so admins can still approve
    # manually.
    #
    # ``spend_id=f"wd:{withdrawal.id}"`` is the **idempotency
    # key** CryptoBot uses to deduplicate Transfer calls on their
    # side. From their docs: "Transfers with the same ``spend_id``
    # will be processed only once." This is the only thing standing
    # between us and a double payout if (a) the network request
    # succeeds but we never see the response (timeout, ASGI worker
    # crash mid-await), and (b) the operator retries the same
    # withdrawal id. The retry hits the same ``spend_id``, CryptoBot
    # returns the already-completed Transfer, and we end up where we
    # started instead of paying out twice. Do NOT include any
    # request-attempt / timestamp suffix in ``spend_id`` — that
    # defeats the point. ``withdrawal.id`` is the natural key
    # because the ``WalletWithdrawal`` row is created **before** the
    # Transfer call, so its id is stable across retries.
    #
    # CRIT #2 — three-phase commit mirrors
    # ``routers/admin/withdrawals.decide_withdrawal``:
    #
    # * Phase 1 (above): debit ``bal.amount`` → ``bal.locked``, insert
    #   the ``pending`` ``WalletWithdrawal`` row, commit. The
    #   ``FOR UPDATE`` lock from ``lock_user_balance`` is released
    #   here so the long CryptoBot HTTP roundtrip below does NOT hold
    #   any DB locks.
    # * Phase 2: CryptoBot HTTP transfer without any DB locks. The
    #   in-memory ``bal`` object is now stale — any other transaction
    #   (admin adjust, another withdraw, deposit webhook) may have
    #   modified ``user_balances`` while we awaited the network.
    # * Phase 3: re-SELECT both ``WalletWithdrawal`` and
    #   ``UserBalance`` with ``FOR UPDATE``, re-check status (an
    #   admin could have rejected the row), decrement ``locked``
    #   atomically against the freshly-locked row, commit. Pre-fix
    #   this branch mutated the stale ``bal`` Python object and
    #   committed it, which silently overwrote any concurrent write
    #   to ``user_balances`` (classic lost-update).
    if await _auto_withdraw_enabled(session) and _cryptopay_configured():
        try:
            async with CryptoPay(
                settings.cryptobot_token, testnet=settings.cryptobot_testnet
            ) as cp:
                tr = await cp.transfer(
                    user_id=user.tg_user_id,
                    asset=currency.code,
                    amount=str(amount),
                    spend_id=f"wd:{withdrawal.id}",
                    comment=f"Garant withdrawal #{withdrawal.id}",
                )
        except CryptoPayError as e:
            logger.warning(
                "auto-withdraw #%s CryptoBot transfer failed: %s — leaving pending",
                withdrawal.id,
                e,
                extra={
                    "event": "cryptobot.auto_withdraw.failed",
                    "withdrawal_id": withdrawal.id,
                    "user_id": user.id,
                    "currency": currency.code,
                    "amount": amount,
                },
            )
        else:
            # Phase 3: re-lock the withdrawal + balance and apply the
            # ``locked`` decrement against the fresh row. We must NOT
            # touch the stale ``bal`` from Phase 1 — it carries
            # in-memory values from before the network call and a
            # naïve ``bal.locked = …`` write would emit
            # ``UPDATE user_balances SET amount=$1, locked=$2 …`` with
            # those stale values, overwriting any concurrent change.
            w_locked = (
                await session.execute(
                    select(WalletWithdrawal)
                    .where(WalletWithdrawal.id == withdrawal.id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if w_locked is None:
                # Row vanished between Phase 1 and Phase 3 (admin
                # delete?). CryptoBot has already shipped — log loudly
                # so an operator can reconcile manually.
                logger.error(
                    "auto-withdraw #%s row vanished before Phase 3",
                    withdrawal.id,
                    extra={
                        "event": "cryptobot.auto_withdraw.row_vanished",
                        "withdrawal_id": withdrawal.id,
                        "cryptobot_transfer_id": tr.transfer_id,
                    },
                )
                return withdrawal
            if w_locked.status == WalletWithdrawStatus.sent:
                # Idempotent replay after a crash between Phase 2 and
                # Phase 3 (CryptoBot dedupes via ``spend_id``); return
                # the already-finalised row.
                return w_locked
            if w_locked.status != WalletWithdrawStatus.pending:
                # An admin rejected/approved the row under us. The
                # transfer has already been shipped by CryptoBot —
                # log so the operator notices the inconsistency.
                logger.error(
                    "auto-withdraw #%s status changed under Phase 3: %s",
                    withdrawal.id,
                    w_locked.status.value,
                    extra={
                        "event": "cryptobot.auto_withdraw.race",
                        "withdrawal_id": withdrawal.id,
                        "observed_status": w_locked.status.value,
                        "cryptobot_transfer_id": tr.transfer_id,
                    },
                )
                return w_locked

            bal_locked = (
                await session.execute(
                    select(UserBalance)
                    .where(
                        UserBalance.user_id == w_locked.user_id,
                        UserBalance.currency_id == w_locked.currency_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if bal_locked is not None:
                bal_locked.locked = max(
                    Decimal(0),
                    Decimal(str(bal_locked.locked)) - amount_d,
                )

            w_locked.status = WalletWithdrawStatus.sent
            w_locked.processed_at = utcnow()
            w_locked.admin_note = f"cryptobot_transfer_id={tr.transfer_id}"
            # A9-M-2 — split-API: persist notification atomically with the
            # "sent" state transition, dispatch WS/DM after commit.
            notif, ws_payload = await notifier.insert(
                session,
                user.id,
                NotificationType.deposits,
                "Вывод выполнен",
                f"-{amount} {currency.code} отправлены на {address}",
                {"withdrawal_id": w_locked.id},
            )
            await session.commit()
            try:
                await notifier.dispatch_after_commit(session, notif, ws_payload)
            except Exception:
                logger.exception(
                    "create_withdrawal: post-commit dispatch failed for notif id=%s",
                    notif.id,
                    extra={
                        "event": "create_withdrawal.auto.dispatch.failed",
                        "notif_id": notif.id,
                    },
                )
            return w_locked

    # Manual mode (or auto failed): queue for admin review.
    # A9-M-2 — same split-API rationale: persist all admin notifications
    # atomically (with the pending withdrawal row), dispatch WS/DM after
    # commit so a transaction rollback can't broadcast "заявка" toasts
    # for a withdrawal that no longer exists.
    admins = (await session.execute(select(User).where(User.is_admin.is_(True)))).scalars().all()
    pending_admin: list[tuple[Notification, dict[str, Any] | None]] = []
    for admin in admins:
        notif, ws_payload = await notifier.insert(
            session,
            admin.id,
            NotificationType.system,
            "Заявка на вывод",
            f"@{user.username or user.tg_user_id}: {amount} {currency.code} → {address[:12]}…",
            {"withdrawal_id": withdrawal.id},
        )
        pending_admin.append((notif, ws_payload))
    if admins:
        await session.commit()
        for notif, ws_payload in pending_admin:
            try:
                await notifier.dispatch_after_commit(session, notif, ws_payload)
            except Exception:
                logger.exception(
                    "create_withdrawal: post-commit dispatch failed for notif id=%s",
                    notif.id,
                    extra={
                        "event": "create_withdrawal.manual.dispatch.failed",
                        "notif_id": notif.id,
                    },
                )

    return withdrawal


# NOTE: the legacy ``decide_withdrawal`` service was removed — the
# canonical admin decide flow now lives in
# ``backend.app.routers.admin.withdrawals.decide_withdrawal`` which
# writes audit rows, holds row locks, and handles auto-mode
# CryptoBot transfers.
