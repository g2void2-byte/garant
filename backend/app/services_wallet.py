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
from .models import (
    AppSettings,
    Currency,
    Notification,
    NotificationType,
    User,
    UserBalance,
    WalletDeposit,
    WalletDepositStatus,
    WalletWithdrawal,
    WalletWithdrawStatus,
)
from .time_utils import utcnow

logger = logging.getLogger(__name__)


# V11-L-1 / A9-L-1 — historically intended as a "dispute window"
# cool-down before the admin queue could act on a user-submitted
# ``WalletWithdrawal`` (see ``WalletWithdrawal.locked_until``
# below). **Enforcement was never wired:**
#
# * ``decide_withdrawal`` (approve / reject / mark_sent) does not
#   check ``locked_until``; admins can act immediately.
# * ``create_withdrawal`` (auto-mode) fires the CryptoBot transfer
#   inline; the cool-down never gates the actual money movement.
# * There is no user-facing ``cancel`` endpoint that consumes the
#   window.
#
# The column is still written on create + read by serializers (so
# external API/typing stays stable), and the constant remains a
# deploy-time knob via ``settings.withdraw_lock_hours``. **A9-I-1**:
# pydantic-settings reads env at ``Settings()`` instantiation, so
# changing the env var requires a restart — this is intentional
# until / unless A9-L-1 enforcement is reintroduced, at which point
# call ``settings.withdraw_lock_hours`` at the use-site instead.
WITHDRAW_LOCK_HOURS = settings.withdraw_lock_hours


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
) -> WalletDeposit:
    if not settings.cryptobot_token or settings.cryptobot_token.startswith("000"):
        raise HTTPException(502, "CryptoBot не настроен")

    currency = await get_currency_by_code(session, currency_code)
    if amount < float(currency.min_deposit):
        raise HTTPException(
            400, f"Минимальная сумма пополнения: {currency.min_deposit} {currency.code}"
        )

    try:
        async with CryptoPay(
            settings.cryptobot_token, testnet=settings.cryptobot_testnet
        ) as crypto:
            invoice = await crypto.create_invoice(asset=currency.code, amount=amount)
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
    # ``purpose`` is validated upstream by
    # ``WalletDepositCreateReq.purpose`` (a ``Literal["wallet", "trust"]``);
    # we still belt-and-suspenders here so non-HTTP callers (admin
    # tooling, tests) can't smuggle an invalid value through the
    # service layer.
    if purpose not in ("wallet", "trust"):
        raise HTTPException(400, f"Неизвестный тип депозита: {purpose}")
    deposit = WalletDeposit(
        user_id=user.id,
        currency_id=currency.id,
        amount=amount,
        provider_invoice_id=str(invoice.invoice_id),
        pay_url=pay_url,
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
        user_row.trust_deposit_balance = Decimal(
            str(user_row.trust_deposit_balance)
        ) + Decimal(str(deposit.amount))
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


async def sweep_expired_deposits(session: AsyncSession) -> int:
    """Mark stale ``pending`` deposits as ``expired``.

    M-6 — pre-fix, a ``WalletDeposit(status=pending)`` row created when
    the user clicked "deposit" but never paid sat in the admin queue
    forever. CryptoBot stops issuing webhooks for the invoice once it
    has expired on their side (default 24h), so the row had no
    independent path to a terminal state. This sweep closes the loop:
    every ``wallet_deposit_sweep_seconds`` the loop in
    :mod:`backend.app.main` runs us and we flip any
    ``pending`` row older than ``wallet_deposit_expiry_seconds`` to
    ``expired``. No balance is credited; the user can always create
    a fresh deposit if they actually wanted to pay.

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

    for row in rows:
        row.status = WalletDepositStatus.expired

    await session.commit()
    return len(rows)


async def poll_deposit_status(session: AsyncSession, deposit: WalletDeposit) -> WalletDeposit:
    """Refresh a pending deposit's status from CryptoBot. Idempotent."""
    if deposit.status != WalletDepositStatus.pending:
        return deposit
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
    if row.status == "expired":
        # Same lock-order rationale as above for the expired branch:
        # serialise with any concurrent webhook delivery on the same
        # row and re-check ``status`` so we never clobber a
        # freshly-paid deposit back to ``expired``.
        # ``populate_existing=True`` for the same identity-map reason
        # documented in the ``paid`` branch above.
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
        await session.commit()
        return locked
    return deposit


# ── Withdrawals ────────────────────────────────────────


async def _auto_withdraw_enabled(session: AsyncSession) -> bool:
    row = (
        await session.execute(select(AppSettings).order_by(AppSettings.id).limit(1))
    ).scalar_one_or_none()
    return bool(row and row.auto_withdraw_enabled)


def _cryptopay_configured() -> bool:
    token = settings.cryptobot_token or ""
    return bool(token) and not token.startswith("000")


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
        locked_until=utcnow() + timedelta(hours=WITHDRAW_LOCK_HOURS),
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
            withdrawal.status = WalletWithdrawStatus.sent
            withdrawal.processed_at = utcnow()
            withdrawal.admin_note = f"cryptobot_transfer_id={tr.transfer_id}"
            bal.locked = max(Decimal(0), Decimal(str(bal.locked)) - amount_d)
            # A9-M-2 — split-API: persist notification atomically with the
            # "sent" state transition, dispatch WS/DM after commit.
            notif, ws_payload = await notifier.insert(
                session,
                user.id,
                NotificationType.deposits,
                "Вывод выполнен",
                f"-{amount} {currency.code} отправлены на {address}",
                {"withdrawal_id": withdrawal.id},
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
            return withdrawal

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
