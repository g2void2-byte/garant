"""Deal escrow on top of the multi-currency wallet (PR-3).

The state machine has 10 statuses (see ``DealStatus`` in ``models.py``).
Money flow uses the per-currency ``UserBalance`` rows introduced in
PR-2 — the legacy ``User.balance`` USD column was retired by H-1 and
no longer exists.

High-level transitions:

    create()                 →  PENDING_CONFIRMATION
    accept   (seller)        →  IN_PROGRESS
    decline  (seller)        →  CANCELLED         (refund buyer)
    finish   (buyer)         →  COMPLETED         (pay seller)
    cancel_request   (any)   →  PENDING_CANCELLATION
    revoke_cancel    (init.) →  IN_PROGRESS
    accept_cancel    (other) →  CANCELLED         (refund buyer)
    debate           (any)   →  ARBITRATION
    resolve          (admin) →  RESOLVED_FOR_{BUYER|SELLER}
    sweep_inactivity (cron)  →  CANCELLED_FOR_INACTIVITY (PC stale)
                                CANCELLED                (PCANC stale)
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from . import notifier
from .models import (
    AppSettings,
    Currency,
    Deal,
    DealStatus,
    Notification,
    NotificationType,
    User,
    UserBalance,
    WalletDeposit,
    WalletDepositStatus,
)
from .money import quantize_money
from .services_ledger import record_balance_ledger
from .services_wallet import get_currency_by_code, lock_user_balance
from .time_utils import utcnow

logger = logging.getLogger(__name__)


async def _safe_dispatch(
    session: AsyncSession,
    pending: list[tuple[Notification, dict[str, Any] | None]],
    *,
    event: str = "deal.dispatch.failed",
) -> None:
    """Fire WS + DM for committed notifications, swallowing delivery errors.

    A9-M-2 — every state-changing deal op now inserts the notification
    row *before* commit (atomic with the deal-row + balance write) and
    dispatches via this helper *after* commit. A rolled-back transaction
    therefore never leaks an event to the user; a failed WS/DM dispatch
    never bubbles up to surface a 500 on an otherwise successful op.
    """
    for notif, ws_payload in pending:
        try:
            await notifier.dispatch_after_commit(session, notif, ws_payload)
        except (TimeoutError, SQLAlchemyError, OSError, RuntimeError):
            # Audit (continuation) M-6 — narrowed from ``except
            # Exception`` for the same reason as the same fan-out
            # helpers in ``services_wallet`` (post-commit dispatch
            # must survive transient I/O failures but not silently
            # swallow programmer bugs).
            # Structured-logging fields so JSON-logger downstream
            # (Loki/Sentry) can pivot on event/notif_id without
            # regexing the message body.
            logger.exception(
                "post-commit dispatch failed for notif id=%s",
                notif.id,
                extra={"event": event, "notif_id": notif.id},
            )


# ── Settings helper ────────────────────────────────────


async def _settings(session: AsyncSession) -> AppSettings:
    # V11-M-7 — the singleton ``app_settings`` row is protected by the
    # unique expression-index ``ix_app_settings_singleton`` (see
    # migration ``d2a7c9b5e4f1``: ``CREATE UNIQUE INDEX ... ON
    # app_settings ((true))``). Pre-fix this helper did a plain
    # ``session.add()`` which, under two parallel cold-start workers,
    # produced an ``IntegrityError`` on the loser of the race.
    #
    # We use the *unqualified* ``ON CONFLICT DO NOTHING`` form
    # (no inference target) because the index is over the
    # expression ``(true)``, and SQLAlchemy's ``index_elements`` /
    # ``index_where`` machinery is designed for plain-column /
    # partial-index inference. The unqualified form is accepted by
    # Postgres for any row-level uniqueness violation on the table
    # and is the right primitive here: ``app_settings`` has only the
    # singleton index, so there is no risk of swallowing an
    # unrelated conflict.
    result = await session.execute(select(AppSettings).limit(1))
    s = result.scalar_one_or_none()
    if s is not None:
        return s
    await session.execute(pg_insert(AppSettings).values().on_conflict_do_nothing())
    await session.commit()
    s = (await session.execute(select(AppSettings).limit(1))).scalar_one_or_none()
    if s is None:  # pragma: no cover — unreachable; either branch above commits a row.
        raise RuntimeError("app_settings row failed to materialise")
    return s


def _commission(amount: Decimal, percent: Decimal | float, decimals: int) -> Decimal:
    return quantize_money(amount * Decimal(str(percent)) / Decimal(100), decimals)


# ── Balance helpers ────────────────────────────────────


class InsufficientFundsError(ValueError):
    """Item 18 — buyer's balance < required deal lock.

    Carries the numbers the frontend needs to render a precise
    "не хватает X" hint (required, balance, deficit, currency code).
    The base ``ValueError`` message stays "Недостаточно средств" so
    existing log lines / tests asserting on it keep working.
    """

    def __init__(
        self,
        *,
        required: Decimal,
        balance: Decimal,
        currency_code: str | None,
    ) -> None:
        super().__init__("Недостаточно средств")
        self.required = required
        self.balance = balance
        self.deficit = required - balance
        self.currency_code = currency_code


async def _debit(
    session: AsyncSession, user_id: int, currency_id: int, amount: Decimal
) -> UserBalance:
    # Row-lock the balance: two concurrent ``create_deal`` calls must
    # not both pass the ``amount >= locked`` check on the same balance.
    bal = await lock_user_balance(session, user_id, currency_id)
    current = Decimal(str(bal.amount))
    before_locked = Decimal(str(bal.locked))
    if current < amount:
        currency = await session.get(Currency, currency_id)
        raise InsufficientFundsError(
            required=amount,
            balance=current,
            currency_code=currency.code if currency is not None else None,
        )
    # Persist as Decimal so SQLAlchemy's ``Numeric(28,8)`` keeps the
    # full 8-fractional-digit precision. Round-tripping through
    # ``float()`` here was the M5 finding — for crypto amounts at the
    # 10^10 scale a ``float`` re-encode drops the last 2-3 significant
    # digits, and the *next* read-modify-write compounds the loss.
    bal.amount = current - amount
    bal.locked = Decimal(str(bal.locked)) + amount
    record_balance_ledger(
        session,
        bal,
        before_amount=current,
        before_locked=before_locked,
        event_type="deal.lock",
        source_type="deal",
        meta={"amount": str(amount)},
    )
    return bal


async def _refund(
    session: AsyncSession, user_id: int, currency_id: int, amount: Decimal
) -> UserBalance:
    # Row-lock the balance: two concurrent finalisers (e.g. parallel
    # ``finish_deal`` + ``decline_deal`` for two distinct deals
    # sharing the same buyer) must not both do a read-modify-write
    # against a stale snapshot of ``UserBalance.amount`` /
    # ``UserBalance.locked``. ``lock_user_balance`` issues
    # ``SELECT ... FOR UPDATE`` so the second caller waits for the
    # first to commit and then re-reads the post-write row before
    # applying its own delta. Lost-update was the original audit
    # CRIT #1 — fixed here at the helper boundary so every refund
    # path (decline / accept_cancel / sweep / arbitration-for-buyer)
    # inherits the lock without duplicating the boilerplate.
    bal = await lock_user_balance(session, user_id, currency_id)
    before_amount = Decimal(str(bal.amount))
    before_locked = Decimal(str(bal.locked))
    bal.locked = max(Decimal(0), Decimal(str(bal.locked)) - amount)
    bal.amount = Decimal(str(bal.amount)) + amount
    record_balance_ledger(
        session,
        bal,
        before_amount=before_amount,
        before_locked=before_locked,
        event_type="deal.refund",
        source_type="deal",
        meta={"amount": str(amount)},
    )
    return bal


async def _refund_principal(
    session: AsyncSession,
    user_id: int,
    currency_id: int,
    principal: Decimal,
) -> UserBalance:
    """Unlock ``principal`` and credit the same amount back to ``amount``.

    P10 — in the commission-via-invoice flow the platform's commission
    is paid out-of-band through the deposit invoice and never enters
    ``UserBalance.locked``; the only thing locked into escrow is the
    deal principal (``Deal.amount``). All refund paths therefore
    simply unlock + credit ``principal`` 1:1 with no commission
    retention math. The pre-P10 helper name
    ``_refund_principal_keep_commission`` was misleading once the
    commission stopped flowing through ``UserBalance`` — the new name
    matches the spec's "refund principal (only what was locked)".
    """
    # Same ``FOR UPDATE`` lock as ``_refund`` above — see that helper's
    # comment for the lost-update rationale.
    bal = await lock_user_balance(session, user_id, currency_id)
    before_amount = Decimal(str(bal.amount))
    before_locked = Decimal(str(bal.locked))
    bal.locked = max(Decimal(0), Decimal(str(bal.locked)) - principal)
    bal.amount = Decimal(str(bal.amount)) + principal
    record_balance_ledger(
        session,
        bal,
        before_amount=before_amount,
        before_locked=before_locked,
        event_type="deal.refund_principal",
        source_type="deal",
        meta={"amount": str(principal)},
    )
    return bal


async def _release_to(
    session: AsyncSession,
    payer_id: int,
    payee_id: int,
    currency_id: int,
    locked_amount: Decimal,
    payout_amount: Decimal,
) -> None:
    """Unlock ``locked_amount`` from payer and credit ``payout_amount`` to payee.

    The diff (``locked_amount - payout_amount``) is the platform commission;
    it stays in payer's locked → effectively "burns" it into the platform
    pool. The platform's own ledger isn't modeled in PR-3.
    """
    # Two row locks — same lost-update rationale as ``_refund``.
    #
    # Audit (continuation) H-1 — deadlock-free ordering. Pre-fix this
    # helper always locked ``payer`` first and ``payee`` second. With
    # one user marketplace it doesn't matter, but two distinct deals
    # between the same pair ``(A, B)`` in *opposite* directions
    # (deal#1: A→B, deal#2: B→A) racing through ``_release_to`` would
    # acquire the two ``UserBalance`` row locks in opposite orders —
    # ``A,B`` for deal#1 and ``B,A`` for deal#2 — and PostgreSQL's
    # deadlock detector would abort one of them with a 40P01 forcing
    # the caller to see ``Transaction aborted, please retry`` 500.
    # Same fix pattern as ``services_account.transfer_account``: sort
    # the two user_ids ascending and lock in that order. The
    # subsequent mutations (decrement payer.locked, increment
    # payee.amount) still target the correct rows because we hold
    # both locks simultaneously when we mutate.
    first_id, second_id = sorted((payer_id, payee_id))
    first = await lock_user_balance(session, first_id, currency_id)
    second = await lock_user_balance(session, second_id, currency_id)
    payer, payee = (first, second) if payer_id == first_id else (second, first)
    payer_before_amount = Decimal(str(payer.amount))
    payer_before_locked = Decimal(str(payer.locked))
    payee_before_amount = Decimal(str(payee.amount))
    payee_before_locked = Decimal(str(payee.locked))
    payer.locked = max(Decimal(0), Decimal(str(payer.locked)) - locked_amount)
    payee.amount = Decimal(str(payee.amount)) + payout_amount
    record_balance_ledger(
        session,
        payer,
        before_amount=payer_before_amount,
        before_locked=payer_before_locked,
        event_type="deal.release_debit",
        source_type="deal",
        meta={"locked_amount": str(locked_amount), "payout_amount": str(payout_amount)},
    )
    record_balance_ledger(
        session,
        payee,
        before_amount=payee_before_amount,
        before_locked=payee_before_locked,
        event_type="deal.release_credit",
        source_type="deal",
        meta={"locked_amount": str(locked_amount), "payout_amount": str(payout_amount)},
    )


# ── Lifecycle ──────────────────────────────────────────


def _resolve_commission_rate(settings: AppSettings, buyer: User, seller: User) -> Decimal:
    """Pick the commission percentage for this buyer/seller pair.

    Per spec, VIP users get a reduced commission rate (set globally in
    ``app_settings.vip_commission_percent``). The override applies
    whenever either side of the deal is VIP and the override is
    non-negative; ``-1`` is the sentinel "no override".
    """
    rate = Decimal(str(settings.deal_commission_percent))
    vip_rate = Decimal(str(settings.vip_commission_percent))
    if vip_rate >= 0 and (buyer.is_vip or seller.is_vip):
        rate = vip_rate
    return rate


async def create_deal(
    session: AsyncSession,
    buyer: User,
    seller: User,
    currency_code: str,
    amount: float | Decimal,
    description: str,
    payment_provider: str = "cryptobot",
) -> Deal:
    """Create a deal and lock buyer funds from their existing balance.

    P10 — the legacy ``pay_commission`` parameter and the
    ``locked = amount + commission`` arithmetic were removed: the
    platform commission is now charged via a deposit invoice (see
    :func:`create_deal_with_topup`). The plain ``create_deal`` path
    funds the deal entirely from ``UserBalance.amount`` and only
    locks ``amount`` — the buyer is expected to have already paid
    commission either via an upfront top-up or via the with-topup
    flow. This entry point is kept for legacy callers / tests that
    have already covered the commission externally; production HTTP
    traffic now routes through :func:`create_deal_with_topup`.

    ``payment_provider`` is the upstream invoice provider the buyer
    picked at deal-create time (``"cryptobot"`` or ``"crystalpay"``)
    — persisted on the deal row for future invoice-driven escrow
    flows.
    """
    if buyer.id == seller.id:
        raise ValueError("Нельзя создать сделку с самим собой")

    currency = await get_currency_by_code(session, currency_code)
    settings = await _settings(session)
    # M-5 — defence-in-depth: the caller is normally
    # ``routers/deals.py`` which already constrains ``DealCreate.amount
    # >= 1e-8`` at the schema layer, but ``create_deal`` is also driven
    # from admin / test helpers / future internal services that may
    # pass a raw value. Reject zero / negative / sub-satoshi values
    # *before* we touch the per-currency quantisation so a non-HTTP
    # caller can't (a) lock a zero-balance escrow, (b) trigger a free
    # commission rounding to zero, or (c) spam pending-confirmation
    # rows against a victim seller.
    raw = Decimal(str(amount))
    if not raw.is_finite() or raw <= 0:
        raise ValueError("Сумма должна быть больше нуля")
    amt = quantize_money(raw, currency.decimals)
    if amt <= 0:
        # ``quantize_money`` rounds half-even at ``currency.decimals``
        # digits, so a positive sub-currency-precision input (e.g.
        # ``Decimal("0.000000001")`` for an 8-decimal asset) lands on
        # zero here. We re-check after the quantise step to keep the
        # post-rounding invariant ``amt > 0`` explicit at the lock
        # site below.
        raise ValueError("Сумма должна быть больше нуля")

    rate = _resolve_commission_rate(settings, buyer, seller)
    commission = _commission(amt, rate, currency.decimals)
    # P10 — lock only the principal. Commission is charged via the
    # deposit invoice path (see ``create_deal_with_topup``) and never
    # touches ``UserBalance.locked``.
    await _debit(session, buyer.id, currency.id, amt)

    deal = Deal(
        buyer_id=buyer.id,
        seller_id=seller.id,
        amount=amt,
        commission_amount=commission,
        currency_id=currency.id,
        description=description,
        status=DealStatus.pending_confirmation,
        payment_provider=payment_provider,
        # Commission was assumed pre-paid before this entry point;
        # see the docstring above. The ``create_deal_with_topup``
        # path is the one that flips this on webhook arrival.
        commission_paid=True,
    )
    session.add(deal)
    # Comment 31 (H, anti-griefing) — ``deals_total`` is bumped on
    # acceptance, not creation. Otherwise a malicious buyer could
    # spam ``POST /api/deals`` against a victim seller (who can only
    # decline 10/min via RLDealCreate, but those 10 still inflate
    # the seller's ``deals_total`` counter) — up to ~10 000 rows over
    # a few days, all visible on the seller's profile until they
    # cancel each one. Moving the increment to ``accept_deal`` /
    # ``finish_deal`` means a pending-confirmation row no longer
    # counts towards the public profile metric.
    await session.flush()
    # A9-M-2 — insert the notification row before commit (atomic with the
    # deal-row + balance debit) but defer WS/DM dispatch until after commit
    # so a rolled-back transaction never leaks an event to the user.
    notif, ws_payload = await notifier.insert(
        session,
        seller.id,
        NotificationType.deals,
        "Новая сделка",
        f"@{buyer.username or buyer.tg_user_id} создал сделку #{deal.id} на {amt} {currency.code}",
        {"deal_id": deal.id},
    )
    await session.commit()
    await _safe_dispatch(session, [(notif, ws_payload)])
    await notifier.publish_deal_update(
        deal.id, [deal.buyer_id, deal.seller_id], status=deal.status.value
    )
    # L-19 — eager-load the ``buyer`` / ``seller`` / ``currency``
    # relationships so the caller's response serialiser
    # (``_deal_out`` / ``_to_detail``) can render
    # ``deal.buyer.username`` / ``deal.currency.code`` without
    # triggering a sync lazy-load on this freshly-INSERTed row.
    # ``lazy="selectin"`` only fires after the row is loaded via a
    # SELECT; an INSERT-only path leaves the relationships unloaded
    # even with ``expire_on_commit=False``. The narrow
    # ``attribute_names=`` form lets us re-fetch *only* the
    # relationships rather than re-SELECT every column.
    await session.refresh(deal, attribute_names=["buyer", "seller", "currency"])
    return deal


# ── Commission-via-invoice flow (P10) ──────────────────


async def create_deal_with_topup(
    session: AsyncSession,
    buyer: User,
    seller: User,
    currency_code: str,
    amount: float | Decimal,
    description: str,
    payment_provider: str = "cryptobot",
) -> tuple[Deal, WalletDeposit | None]:
    """Create a deal that's funded by an outstanding deposit invoice
    OR fully covered by the buyer's wallet balance.

    P10 — replaces the legacy ``create_deal`` HTTP entry point. The
    buyer no longer needs to pre-deposit funds; instead the platform
    issues a single deposit invoice covering:

    * the difference between ``amount`` and the buyer's current
      ``UserBalance.amount`` (``topup_principal = max(0, amount - balance)``)
    * plus the platform commission (``commission = amount * rate / 100``)

    so ``invoice_total = topup_principal + commission``. When the
    buyer's balance already covers ``amount``, ``topup_principal = 0``
    and the invoice charges only the commission.

    P11-D1 — when the buyer's balance already covers
    ``amount + commission``, we skip the invoice path entirely:
    the principal moves to ``UserBalance.locked``, the commission
    is debited from ``UserBalance.amount`` (the platform's share —
    same accounting as the upstream-provider branch where CryptoBot
    keeps the commission portion), the deal lands in
    :data:`DealStatus.pending_confirmation` with ``commission_paid=True``,
    and the return is ``(deal, None)`` so the router can skip the
    pay-invoice UI.

    Otherwise the deal is created in :data:`DealStatus.pending_topup`
    and the invoice is linked through ``Deal.topup_deposit_id`` /
    ``WalletDeposit.linked_deal_id``. The webhook handler
    (:func:`complete_deal_topup_payment`) credits the deposit, locks
    the principal, and advances the deal to
    :data:`DealStatus.pending_confirmation` once enough has been
    paid. Underpayment / overpayment / commission-only edge cases
    are documented on that helper.
    """
    # ``create_deposit_invoice`` is imported lazily because
    # ``services_wallet`` already pulls ``services_deals`` indirectly
    # through ``credit_deposit`` → ``complete_deal_topup_payment``.
    # Same cycle-breaking pattern as the ``credit_deposit`` branch in
    # ``services_wallet``.
    from .services_wallet import create_deposit_invoice, lock_user_balance

    if buyer.id == seller.id:
        raise ValueError("Нельзя создать сделку с самим собой")

    currency = await get_currency_by_code(session, currency_code)
    settings = await _settings(session)

    raw = Decimal(str(amount))
    if not raw.is_finite() or raw <= 0:
        raise ValueError("Сумма должна быть больше нуля")
    amt = quantize_money(raw, currency.decimals)
    if amt <= 0:
        raise ValueError("Сумма должна быть больше нуля")

    rate = _resolve_commission_rate(settings, buyer, seller)
    commission = _commission(amt, rate, currency.decimals)

    bal = await lock_user_balance(session, buyer.id, currency.id)
    balance_amount = Decimal(str(bal.amount))
    needed = quantize_money(amt + commission, currency.decimals)
    topup_principal = max(Decimal(0), amt - balance_amount)
    topup_principal = quantize_money(topup_principal, currency.decimals)
    invoice_total = quantize_money(topup_principal + commission, currency.decimals)

    # P11-D1 — balance-fully-covers branch. The buyer has enough on
    # ``UserBalance.amount`` to cover both the principal and the
    # commission, so the upstream invoice round-trip is pointless
    # (and would either bounce on ``min_deposit`` for tiny
    # commissions or just inconvenience the user with an extra
    # CryptoBot tab). Move the principal to ``locked`` and burn the
    # commission off ``amount`` — the platform's commission share is
    # already accounted for the same way the invoice path does it
    # (CryptoBot keeps the commission portion of the upstream
    # invoice, so the user-side ledger never sees that money).
    if balance_amount >= needed:
        balance_before_amount = Decimal(str(bal.amount))
        balance_before_locked = Decimal(str(bal.locked))
        bal.amount = balance_amount - needed
        bal.locked = Decimal(str(bal.locked)) + amt
        deal = Deal(
            buyer_id=buyer.id,
            seller_id=seller.id,
            amount=amt,
            commission_amount=commission,
            currency_id=currency.id,
            description=description,
            status=DealStatus.pending_confirmation,
            payment_provider=payment_provider,
            commission_paid=True,
        )
        session.add(deal)
        await session.flush()
        record_balance_ledger(
            session,
            bal,
            before_amount=balance_before_amount,
            before_locked=balance_before_locked,
            event_type="deal.create_balance_funded",
            source_type="deal",
            source_id=deal.id,
            meta={"commission": str(commission), "principal": str(amt)},
        )
        notif, ws_payload = await notifier.insert(
            session,
            seller.id,
            NotificationType.deals,
            "Новая сделка",
            (
                f"@{buyer.username or buyer.tg_user_id} создал сделку #{deal.id} "
                f"на {amt} {currency.code}"
            ),
            {"deal_id": deal.id},
        )
        await session.commit()
        await _safe_dispatch(session, [(notif, ws_payload)])
        await notifier.publish_deal_update(
            deal.id, [deal.buyer_id, deal.seller_id], status=deal.status.value
        )
        await session.refresh(deal, attribute_names=["buyer", "seller", "currency"])
        return deal, None

    deal = Deal(
        buyer_id=buyer.id,
        seller_id=seller.id,
        amount=amt,
        commission_amount=commission,
        currency_id=currency.id,
        description=description,
        status=DealStatus.pending_topup,
        payment_provider=payment_provider,
        commission_paid=False,
    )
    session.add(deal)
    await session.flush()

    if invoice_total <= 0:
        # Edge case kept from the original P10 contract: ``amt`` is so
        # small (vs. the commission rate) that ``commission``
        # quantises to zero AND ``balance >= amt`` (otherwise the
        # balance-fully-covers branch above would have fired).
        # ``balance >= amt + 0`` would in fact land us in that
        # branch, so this is mostly defensive — we keep the explicit
        # raise to surface a developer error if someone widens the
        # commission rate range later.
        raise ValueError("Сумма комиссии меньше точности валюты — используйте обычную сделку")

    # Issue the deposit invoice on the buyer's chosen provider. Note
    # the float() coercion: ``create_deposit_invoice`` accepts
    # ``float`` because the upstream provider clients (CryptoBot,
    # Crystalpay) consume floats; the row itself stores the Decimal
    # back via ``Numeric(28,8)`` so no precision is lost on the way.
    #
    # P11-D1 — ``min_check=False`` is the escape hatch for the
    # commission-only edge case: when the buyer's balance covers
    # the principal but not ``commission`` (so the invoice charges
    # JUST the commission, which can be smaller than the per-currency
    # ``min_deposit``). The HTTP wallet-deposit endpoint still
    # enforces ``min_deposit`` for direct top-ups; only this internal
    # caller bypasses it because the deal flow has no UX way to ask
    # the user to "top up at least 1 USD" when they only need to pay
    # a 0.50 USD commission.
    skip_min = invoice_total < Decimal(str(currency.min_deposit))
    deposit = await create_deposit_invoice(
        session,
        buyer,
        currency.code,
        float(invoice_total),
        purpose="deal_topup",
        provider=payment_provider,
        min_check=not skip_min,
        commit=False,
    )
    deposit.linked_deal_id = deal.id
    deal.topup_deposit_id = deposit.id

    notif, ws_payload = await notifier.insert(
        session,
        seller.id,
        NotificationType.deals,
        "Новая сделка (ожидает оплату)",
        (
            f"@{buyer.username or buyer.tg_user_id} создал сделку #{deal.id} "
            f"на {amt} {currency.code}. Ждём оплату счёта покупателем."
        ),
        {"deal_id": deal.id},
    )
    await session.commit()
    await _safe_dispatch(session, [(notif, ws_payload)])
    await notifier.publish_deal_update(
        deal.id, [deal.buyer_id, deal.seller_id], status=deal.status.value
    )
    await session.refresh(deal, attribute_names=["buyer", "seller", "currency"])
    await session.refresh(deposit, attribute_names=["currency"])
    return deal, deposit


async def _issue_remaining_topup_invoice(
    session: AsyncSession,
    deal: Deal,
    currency: Currency,
    current_balance: Decimal,
) -> WalletDeposit | None:
    """Attach a fresh top-up invoice for the remaining activation gap."""
    from .services_wallet import create_deposit_invoice

    buyer = await session.get(User, deal.buyer_id)
    if buyer is None:
        raise ValueError("buyer vanished")

    amt = quantize_money(Decimal(str(deal.amount)), currency.decimals)
    commission = quantize_money(Decimal(str(deal.commission_amount or 0)), currency.decimals)
    commission_due = Decimal("0") if deal.commission_paid else commission
    principal_gap = max(Decimal("0"), amt - current_balance)
    invoice_total = quantize_money(principal_gap + commission_due, currency.decimals)
    if invoice_total <= 0:
        return None

    deposit = await create_deposit_invoice(
        session,
        buyer,
        currency.code,
        float(invoice_total),
        purpose="deal_topup",
        provider=deal.payment_provider or "cryptobot",
        min_check=False,
        commit=False,
    )
    deposit.linked_deal_id = deal.id
    deal.topup_deposit_id = deposit.id
    return deposit


async def complete_deal_topup_payment(
    session: AsyncSession,
    deposit: WalletDeposit,
    *,
    paid_amount: Decimal | float | None = None,
) -> WalletDeposit:
    """Webhook callback for a paid ``purpose='deal_topup'`` deposit.

    Idempotent — short-circuits when the deposit is already ``paid``.
    Algorithm (spec):

    * ``paid = paid_amount or deposit.amount``
    * ``commission_due`` is zero once a previous partial payment has
      already covered the commission.
    * If ``paid < commission_due``: credit the full ``paid`` to the
      buyer's ``UserBalance.amount``; the deal stays ``pending_topup``;
      attach a new invoice for the remaining principal + commission.
    * Else: credit ``paid - commission_due`` to the buyer's balance,
      mark the commission collected, and re-check ``balance >= deal.amount``.
      If yes: lock ``deal.amount`` into ``UserBalance.locked`` and advance
      to ``pending_confirmation``. If no: stay ``pending_topup`` and attach
      a new invoice for the remaining principal.

    Lock order: ``WalletDeposit (already locked by caller) → Deal →
    UserBalance``. The deposit row is the canonical entry point in
    the deposit-webhook flow so we don't take a redundant lock on
    it here; the deal + balance locks run in stable id order.
    """
    from .services_wallet import lock_user_balance

    if deposit.status == WalletDepositStatus.paid:
        return deposit

    if deposit.linked_deal_id is None:
        # Defensive — a deal_topup deposit MUST be linked to a deal.
        # Without that we can't settle anything; flag the row paid
        # (so the upstream provider stops retrying the webhook) and
        # surface a loud log entry. The user's payment is effectively
        # an unattached deposit; SRE can reconcile manually.
        deposit.status = WalletDepositStatus.paid
        deposit.paid_at = utcnow()
        if paid_amount is not None:
            deposit.paid_amount = Decimal(str(paid_amount))
        await session.commit()
        logger.error(
            "deal_topup deposit %s paid with no linked deal",
            deposit.id,
            extra={"event": "deal_topup.unlinked", "deposit_id": deposit.id},
        )
        return deposit

    deal = (
        await session.execute(
            select(Deal).where(Deal.id == deposit.linked_deal_id).with_for_update()
        )
    ).scalar_one_or_none()
    if deal is None:
        deposit.status = WalletDepositStatus.paid
        deposit.paid_at = utcnow()
        if paid_amount is not None:
            deposit.paid_amount = Decimal(str(paid_amount))
        await session.commit()
        logger.error(
            "deal_topup deposit %s linked deal %s not found",
            deposit.id,
            deposit.linked_deal_id,
            extra={
                "event": "deal_topup.deal_missing",
                "deposit_id": deposit.id,
                "deal_id": deposit.linked_deal_id,
            },
        )
        return deposit

    currency = await session.get(Currency, deal.currency_id)
    if currency is None:
        raise ValueError("currency vanished")

    paid = Decimal(str(paid_amount)) if paid_amount is not None else Decimal(str(deposit.amount))
    paid = quantize_money(paid, currency.decimals)

    if deal.status != DealStatus.pending_topup:
        bal = await lock_user_balance(session, deal.buyer_id, currency.id)
        before_amount = Decimal(str(bal.amount))
        before_locked = Decimal(str(bal.locked))
        bal.amount = Decimal(str(bal.amount)) + paid
        record_balance_ledger(
            session,
            bal,
            before_amount=before_amount,
            before_locked=before_locked,
            event_type="deal_topup.late_credit",
            source_type="deposit",
            source_id=deposit.id,
            provider=deposit.provider.value,
            provider_event_id=deposit.provider_invoice_id,
            meta={"deal_id": deal.id, "paid": str(paid)},
        )
        deposit.status = WalletDepositStatus.paid
        deposit.paid_at = utcnow()
        deposit.paid_amount = paid
        notif, ws_payload = await notifier.insert(
            session,
            deal.buyer_id,
            NotificationType.deposits,
            "Позднее зачисление",
            f"Поступила оплата {paid} {currency.code} по закрытой сделке #{deal.id}. "
            "Средства зачислены на баланс.",
            {"deposit_id": deposit.id, "currency": currency.code, "deal_id": deal.id},
        )
        await session.commit()
        try:
            await notifier.dispatch_after_commit(session, notif, ws_payload)
        except (TimeoutError, SQLAlchemyError, OSError, RuntimeError):
            logger.exception(
                "complete_deal_topup_payment: late-payment post-commit dispatch "
                "failed for notif id=%s",
                notif.id,
                extra={"event": "deal_topup.late_payment.dispatch.failed", "notif_id": notif.id},
            )
        return deposit

    amt = quantize_money(Decimal(str(deal.amount)), currency.decimals)
    commission = quantize_money(Decimal(str(deal.commission_amount or 0)), currency.decimals)
    commission_due = Decimal("0") if deal.commission_paid else commission

    bal = await lock_user_balance(session, deal.buyer_id, currency.id)
    balance_amount = Decimal(str(bal.amount))
    balance_locked = Decimal(str(bal.locked))

    pending: list[tuple[Notification, dict[str, Any] | None]] = []

    if paid < commission_due:
        # Spec: principal_credit < 0 → all paid goes to balance, deal
        # stays pending_topup. Commission stays uncollected on the
        # platform side (the wallet provider still has the money but
        # we route it back into the buyer's spendable balance per
        # spec). Buyer is asked to top up the rest.
        new_balance = balance_amount + paid
        bal.amount = new_balance
        record_balance_ledger(
            session,
            bal,
            before_amount=balance_amount,
            before_locked=balance_locked,
            event_type="deal_topup.partial_credit",
            source_type="deposit",
            source_id=deposit.id,
            provider=deposit.provider.value,
            provider_event_id=deposit.provider_invoice_id,
            meta={"deal_id": deal.id, "paid": str(paid), "commission_due": str(commission_due)},
        )
        deposit.status = WalletDepositStatus.paid
        deposit.paid_at = utcnow()
        deposit.paid_amount = paid
        replacement = await _issue_remaining_topup_invoice(session, deal, currency, new_balance)
        deficit = Decimal(str(replacement.amount)) if replacement is not None else Decimal("0")
        notif, ws_payload = await notifier.insert(
            session,
            deal.buyer_id,
            NotificationType.deals,
            "Недостаточная оплата по сделке",
            (
                f"По сделке #{deal.id} получено {paid} {currency.code}. "
                f"Требуется ещё около {deficit} {currency.code} для активации."
            ),
            {
                "deal_id": deal.id,
                "deposit_id": deposit.id,
                "replacement_deposit_id": replacement.id if replacement is not None else None,
                "kind": "underpayment",
            },
        )
        pending.append((notif, ws_payload))
        await session.commit()
        await _safe_dispatch(session, pending)
        await notifier.publish_deal_update(
            deal.id, [deal.buyer_id, deal.seller_id], status=deal.status.value
        )
        return deposit

    # ``paid >= commission_due``. The principal_credit is what's left
    # after deducting any commission not already collected by an earlier
    # partial payment.
    principal_credit = quantize_money(paid - commission_due, currency.decimals)
    bal.amount = balance_amount + principal_credit
    if commission_due > 0:
        deal.commission_paid = True

    # Re-read post-credit balance so the lock check below uses the
    # post-credit value.
    new_balance = Decimal(str(bal.amount))
    if new_balance < amt:
        # Commission was paid but the balance is still short of the
        # principal. Stay pending_topup; the buyer needs to top up
        # the remaining gap. ``commission_paid`` stays False per
        # spec — the field flips only when the deal actually
        # advances.
        deposit.status = WalletDepositStatus.paid
        deposit.paid_at = utcnow()
        deposit.paid_amount = paid
        record_balance_ledger(
            session,
            bal,
            before_amount=balance_amount,
            before_locked=balance_locked,
            event_type="deal_topup.partial_credit",
            source_type="deposit",
            source_id=deposit.id,
            provider=deposit.provider.value,
            provider_event_id=deposit.provider_invoice_id,
            meta={"deal_id": deal.id, "paid": str(paid), "commission_due": str(commission_due)},
        )
        replacement = await _issue_remaining_topup_invoice(session, deal, currency, new_balance)
        deficit = Decimal(str(replacement.amount)) if replacement is not None else Decimal("0")
        notif, ws_payload = await notifier.insert(
            session,
            deal.buyer_id,
            NotificationType.deals,
            "Недостаточная оплата по сделке",
            (
                f"По сделке #{deal.id} получено {paid} {currency.code}. "
                f"Не хватает ещё {deficit} {currency.code} на баланс."
            ),
            {
                "deal_id": deal.id,
                "deposit_id": deposit.id,
                "replacement_deposit_id": replacement.id if replacement is not None else None,
                "kind": "underpayment",
            },
        )
        pending.append((notif, ws_payload))
        await session.commit()
        await _safe_dispatch(session, pending)
        await notifier.publish_deal_update(
            deal.id, [deal.buyer_id, deal.seller_id], status=deal.status.value
        )
        return deposit

    # Happy path — lock the principal and advance the deal.
    bal.amount = new_balance - amt
    bal.locked = Decimal(str(bal.locked)) + amt
    record_balance_ledger(
        session,
        bal,
        before_amount=balance_amount,
        before_locked=balance_locked,
        event_type="deal_topup.activate",
        source_type="deposit",
        source_id=deposit.id,
        provider=deposit.provider.value,
        provider_event_id=deposit.provider_invoice_id,
        meta={"deal_id": deal.id, "paid": str(paid), "commission_due": str(commission_due)},
    )
    deposit.status = WalletDepositStatus.paid
    deposit.paid_at = utcnow()
    deposit.paid_amount = paid
    deal.status = DealStatus.pending_confirmation
    deal.commission_paid = True

    notif, ws_payload = await notifier.insert(
        session,
        deal.seller_id,
        NotificationType.deals,
        "Сделка активирована",
        (f"Покупатель оплатил сделку #{deal.id}. Подтвердите участие, чтобы перейти к работе."),
        {"deal_id": deal.id},
    )
    pending.append((notif, ws_payload))
    notif_b, ws_b = await notifier.insert(
        session,
        deal.buyer_id,
        NotificationType.deals,
        "Оплата получена",
        f"Сделка #{deal.id} ожидает подтверждения продавцом.",
        {"deal_id": deal.id},
    )
    pending.append((notif_b, ws_b))
    await session.commit()
    await _safe_dispatch(session, pending)
    await notifier.publish_deal_update(
        deal.id, [deal.buyer_id, deal.seller_id], status=deal.status.value
    )
    return deposit


async def sweep_pending_topup(session: AsyncSession) -> int:
    """Auto-cancel deals stuck in ``pending_topup`` past expiry.

    Mirrors :func:`sweep_inactivity` but uses the dedicated
    ``app_settings.pending_topup_expiry_hours`` window (default 24 h)
    so the operator can tune the deposit-invoice grace period
    independently from the seller-confirmation window. Linked
    deposits are flipped to ``expired`` so they no longer surface
    in the user's wallet ``pending`` list.
    """
    settings = await _settings(session)
    expiry_hours = int(settings.pending_topup_expiry_hours or 24)
    if expiry_hours <= 0:
        return 0
    cutoff = utcnow() - timedelta(hours=expiry_hours)

    rows = (
        (
            await session.execute(
                select(Deal)
                .where(
                    Deal.status == DealStatus.pending_topup,
                    Deal.created_at <= cutoff,
                )
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )

    pending_dispatch: list[tuple[Notification, dict[str, Any] | None]] = []
    for deal in rows:
        # Expire the linked deposit (if still pending) so the wallet
        # provider's stale invoice no longer surfaces in the user's
        # list. We don't refund anything from ``UserBalance`` — the
        # deal never locked principal in the pending_topup state.
        if deal.topup_deposit_id is not None:
            deposit = (
                await session.execute(
                    select(WalletDeposit)
                    .where(WalletDeposit.id == deal.topup_deposit_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if deposit is not None and deposit.status == WalletDepositStatus.pending:
                deposit.status = WalletDepositStatus.expired
        deal.status = DealStatus.cancelled_for_inactivity
        deal.completed_at = utcnow()
        for recipient_id in (deal.buyer_id, deal.seller_id):
            notif, ws_payload = await notifier.insert(
                session,
                recipient_id,
                NotificationType.deals,
                "Сделка отменена за неактивность",
                f"Сделка #{deal.id} закрыта — оплата не поступила.",
                {"deal_id": deal.id},
            )
            pending_dispatch.append((notif, ws_payload))

    await session.commit()
    await _safe_dispatch(session, pending_dispatch, event="sweep_pending_topup.dispatch.failed")
    for deal in rows:
        await notifier.publish_deal_update(
            deal.id, [deal.buyer_id, deal.seller_id], status=deal.status.value
        )
    return len(rows)


async def cancel_pending_topup(session: AsyncSession, deal: Deal, user: User) -> Deal:
    """P10 — buyer-side cancel for a deal still in ``pending_topup``.

    Mirrors :func:`sweep_pending_topup` but acts on a single deal
    surfaced through the buyer-initiated cancel button on the deal
    detail page. Only the buyer can call this; the deal must still
    be in ``pending_topup`` (no half-paid in-flight states). Linked
    deposit row is flipped to ``expired`` so the upstream invoice
    stops surfacing in the wallet pending list; nothing is refunded
    from ``UserBalance`` because nothing was ever locked.
    """
    if user.id != deal.buyer_id:
        raise ValueError("Отменить ожидающую оплату сделку может только покупатель")
    if deal.status != DealStatus.pending_topup:
        raise ValueError("Сделку нельзя отменить в текущем статусе")

    if deal.topup_deposit_id is not None:
        deposit = (
            await session.execute(
                select(WalletDeposit)
                .where(WalletDeposit.id == deal.topup_deposit_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if deposit is not None and deposit.status == WalletDepositStatus.pending:
            deposit.status = WalletDepositStatus.expired

    deal.status = DealStatus.cancelled
    deal.completed_at = utcnow()

    pending: list[tuple[Notification, dict[str, Any] | None]] = []
    notif, ws_payload = await notifier.insert(
        session,
        deal.seller_id,
        NotificationType.deals,
        "Сделка отменена покупателем",
        f"Сделка #{deal.id} отменена — оплата не поступила.",
        {"deal_id": deal.id},
    )
    pending.append((notif, ws_payload))
    await session.commit()
    await _safe_dispatch(session, pending)
    await notifier.publish_deal_update(
        deal.id, [deal.buyer_id, deal.seller_id], status=deal.status.value
    )
    return deal


async def accept_deal(session: AsyncSession, deal: Deal, user: User) -> Deal:
    if user.id != deal.seller_id:
        raise ValueError("Принять сделку может только продавец")
    if deal.status != DealStatus.pending_confirmation:
        raise ValueError("Сделку нельзя принять в текущем статусе")

    deal.status = DealStatus.in_progress
    deal.in_progress_at = utcnow()
    deal.confirm_buyer = True
    deal.confirm_seller = True
    # Comment 31 (H) — bump ``deals_total`` only once the seller has
    # accepted, so unilateral spam from a malicious buyer can't
    # inflate the seller's public profile counter.
    #
    # V11-H-3 — issue a single SQL ``UPDATE users SET deals_total =
    # deals_total + 1 WHERE id IN (...)`` instead of the previous
    # ``session.get`` + Python ``+= 1`` + commit pattern. The old
    # pattern read-modify-wrote in Python so two concurrent
    # ``accept_deal`` transactions touching the same user could both
    # load the same counter value, both add one, and one commit would
    # overwrite the other — under load the public profile counter
    # silently drifted downward. The new pattern hands the increment
    # to Postgres which serialises row-level writes for us.
    await session.execute(
        update(User)
        .where(User.id.in_([deal.buyer_id, deal.seller_id]))
        .values(deals_total=User.deals_total + 1)
    )
    # A9-M-2 — split-API: persist notification atomically, dispatch after commit.
    notif, ws_payload = await notifier.insert(
        session,
        deal.buyer_id,
        NotificationType.deals,
        "Сделка принята",
        f"Продавец принял сделку #{deal.id}",
        {"deal_id": deal.id},
    )
    await session.commit()
    await _safe_dispatch(session, [(notif, ws_payload)])
    await notifier.publish_deal_update(
        deal.id, [deal.buyer_id, deal.seller_id], status=deal.status.value
    )
    return deal


async def decline_deal(session: AsyncSession, deal: Deal, user: User) -> Deal:
    if user.id != deal.seller_id:
        raise ValueError("Отклонить сделку может только продавец")
    if deal.status != DealStatus.pending_confirmation:
        raise ValueError("Сделку нельзя отклонить в текущем статусе")
    if deal.currency_id is None or deal.amount is None:
        raise ValueError("У сделки не задана валюта")

    currency = await session.get(Currency, deal.currency_id)
    # V11-L-18 — ``assert`` is stripped under ``python -O`` so it is
    # not a safety net in production. The ``deal.currency_id is None``
    # guard above already protects the happy path; the explicit raise
    # here covers the (otherwise impossible) case where the currency
    # row got deleted out from under us.
    if currency is None:
        raise ValueError("currency vanished")
    amt = quantize_money(Decimal(str(deal.amount)), currency.decimals)
    # P10 — commission is on the platform (paid via deposit invoice)
    # and never enters ``UserBalance.locked``. Refund only the
    # principal; commission is NOT returned to the buyer per spec.
    await _refund_principal(session, deal.buyer_id, currency.id, amt)
    commission_clause = "комиссия удержана" if deal.commission_paid else "комиссия не взималась"

    deal.status = DealStatus.cancelled
    deal.completed_at = utcnow()
    # A9-M-2 — split-API: persist notification atomically, dispatch after commit.
    notif, ws_payload = await notifier.insert(
        session,
        deal.buyer_id,
        NotificationType.deals,
        "Сделка отклонена",
        f"Продавец отклонил сделку #{deal.id}. Сумма возвращена; {commission_clause}.",
        {"deal_id": deal.id},
    )
    await session.commit()
    await _safe_dispatch(session, [(notif, ws_payload)])
    await notifier.publish_deal_update(
        deal.id, [deal.buyer_id, deal.seller_id], status=deal.status.value
    )
    return deal


async def finish_deal(session: AsyncSession, deal: Deal, user: User) -> Deal:
    if user.id != deal.buyer_id:
        raise ValueError("Завершить сделку может только покупатель")
    if deal.status != DealStatus.in_progress:
        raise ValueError("Сделку нельзя завершить в текущем статусе")
    if deal.currency_id is None or deal.amount is None:
        raise ValueError("У сделки не задана валюта")

    currency = await session.get(Currency, deal.currency_id)
    # V11-L-18 — explicit raise instead of ``assert`` (which is
    # stripped under ``python -O``).
    if currency is None:
        raise ValueError("currency vanished")
    amt = quantize_money(Decimal(str(deal.amount)), currency.decimals)

    # P10 — seller receives the full ``amount`` because the platform
    # commission was already collected via the deposit invoice path.
    # Locked pot equals the principal; commission never entered
    # ``UserBalance.locked``.
    await _release_to(session, deal.buyer_id, deal.seller_id, currency.id, amt, amt)
    payout = amt

    deal.status = DealStatus.completed
    deal.completed_at = utcnow()
    # V11-H-3 — atomic counter bump; see comment in ``accept_deal``.
    await session.execute(
        update(User)
        .where(User.id.in_([deal.buyer_id, deal.seller_id]))
        .values(deals_success=User.deals_success + 1)
    )
    # A9-M-2 — split-API: persist notification atomically, dispatch after commit.
    notif, ws_payload = await notifier.insert(
        session,
        deal.seller_id,
        NotificationType.deals,
        "Сделка завершена",
        f"Вы получили {payout} {currency.code} по сделке #{deal.id}",
        {"deal_id": deal.id},
    )
    await session.commit()
    await _safe_dispatch(session, [(notif, ws_payload)])
    await notifier.publish_deal_update(
        deal.id, [deal.buyer_id, deal.seller_id], status=deal.status.value
    )
    return deal


# ── Cancel-debate (soft cancel) ────────────────────────


async def request_cancel(session: AsyncSession, deal: Deal, user: User, reason: str) -> Deal:
    if user.id not in (deal.buyer_id, deal.seller_id):
        raise ValueError("Вы не участник сделки")
    if deal.status != DealStatus.in_progress:
        raise ValueError("Отмену можно запросить только во время работы по сделке")

    deal.status = DealStatus.pending_cancellation
    deal.cancellation_initiator_id = user.id
    deal.cancellation_reason = reason
    deal.cancellation_requested_at = utcnow()
    other_id = deal.seller_id if user.id == deal.buyer_id else deal.buyer_id
    # A9-M-2 — split-API: persist notification atomically, dispatch after commit.
    notif, ws_payload = await notifier.insert(
        session,
        other_id,
        NotificationType.deals,
        "Запрос отмены",
        f"По сделке #{deal.id} запрошена отмена: {reason or '—'}",
        {"deal_id": deal.id},
    )
    await session.commit()
    await _safe_dispatch(session, [(notif, ws_payload)])
    await notifier.publish_deal_update(
        deal.id, [deal.buyer_id, deal.seller_id], status=deal.status.value
    )
    return deal


async def revoke_cancel(session: AsyncSession, deal: Deal, user: User) -> Deal:
    if deal.status != DealStatus.pending_cancellation:
        raise ValueError("Запроса на отмену нет")
    if user.id != deal.cancellation_initiator_id:
        raise ValueError("Отозвать запрос может только инициатор")

    deal.status = DealStatus.in_progress
    deal.cancellation_initiator_id = None
    deal.cancellation_reason = None
    deal.cancellation_requested_at = None
    other_id = deal.seller_id if user.id == deal.buyer_id else deal.buyer_id
    # A9-M-2 — split-API: persist notification atomically, dispatch after commit.
    notif, ws_payload = await notifier.insert(
        session,
        other_id,
        NotificationType.deals,
        "Запрос отмены отозван",
        f"По сделке #{deal.id} запрос отмены отозван",
        {"deal_id": deal.id},
    )
    await session.commit()
    await _safe_dispatch(session, [(notif, ws_payload)])
    await notifier.publish_deal_update(
        deal.id, [deal.buyer_id, deal.seller_id], status=deal.status.value
    )
    return deal


async def accept_cancel(session: AsyncSession, deal: Deal, user: User) -> Deal:
    if deal.status != DealStatus.pending_cancellation:
        raise ValueError("Запроса на отмену нет")
    if user.id not in (deal.buyer_id, deal.seller_id):
        raise ValueError("Вы не участник сделки")
    if user.id == deal.cancellation_initiator_id:
        raise ValueError("Инициатор не может согласиться с собственным запросом отмены")
    if deal.currency_id is None or deal.amount is None:
        raise ValueError("У сделки не задана валюта")

    currency = await session.get(Currency, deal.currency_id)
    # V11-L-18 — explicit raise instead of ``assert``.
    if currency is None:
        raise ValueError("currency vanished")
    amt = quantize_money(Decimal(str(deal.amount)), currency.decimals)
    # P10 — refund only the principal; commission already on platform
    # (paid via deposit invoice) and not returned on cancel.
    await _refund_principal(session, deal.buyer_id, currency.id, amt)
    commission_clause = "комиссия удержана" if deal.commission_paid else "комиссия не взималась"

    deal.status = DealStatus.cancelled
    deal.completed_at = utcnow()
    # A9-M-2 + Audit M2 — split-API: persist notifications atomically,
    # dispatch after commit. Both buyer and seller receive the
    # "deal cancelled" event so the accepter's notification feed mirrors
    # the initiator's (pre-fix only ``cancellation_initiator_id`` got a
    # row, which left the accepter without a badge / DM record of the
    # final state).
    body_text = f"По сделке #{deal.id} отмена согласована. Сумма возвращена; {commission_clause}."
    pending: list[tuple[Notification, dict[str, Any] | None]] = []
    seen: set[int] = set()
    for recipient_id in (deal.buyer_id, deal.seller_id):
        if recipient_id in seen:
            continue
        seen.add(recipient_id)
        notif, ws_payload = await notifier.insert(
            session,
            recipient_id,
            NotificationType.deals,
            "Сделка отменена",
            body_text,
            {"deal_id": deal.id},
        )
        pending.append((notif, ws_payload))
    await session.commit()
    await _safe_dispatch(session, pending)
    await notifier.publish_deal_update(
        deal.id, [deal.buyer_id, deal.seller_id], status=deal.status.value
    )
    return deal


# ── Arbitration ────────────────────────────────────────


_ARBITRATION_ELIGIBLE = (
    DealStatus.in_progress,
    DealStatus.pending_cancellation,
)


async def start_arbitration(session: AsyncSession, deal: Deal, user: User, reason: str) -> Deal:
    if user.id not in (deal.buyer_id, deal.seller_id):
        raise ValueError("Вы не участник сделки")
    if deal.status not in _ARBITRATION_ELIGIBLE:
        raise ValueError("Сделку нельзя передать в арбитраж в текущем статусе")
    if not reason or not reason.strip():
        raise ValueError("Опишите причину арбитража")

    deal.status = DealStatus.arbitration
    deal.arbitration_initiator_id = user.id
    deal.arbitration_reason = reason

    # V11-H-3 — atomic counter bump; see comment in ``accept_deal``.
    await session.execute(
        update(User)
        .where(User.id.in_([deal.buyer_id, deal.seller_id]))
        .values(deals_arbitrage=User.deals_arbitrage + 1)
    )

    arbiters = (
        (await session.execute(select(User).where(User.is_arbiter.is_(True)))).scalars().all()
    )
    admins = (await session.execute(select(User).where(User.is_admin.is_(True)))).scalars().all()
    seen: set[int] = set()
    # A9-M-2 — split-API: insert all notifications atomically with the
    # state transition, dispatch WS/DM after commit so a rollback can
    # never leak events.
    pending: list[tuple[Notification, dict[str, Any] | None]] = []
    arbiter_ids: list[int] = []
    for recipient in [*arbiters, *admins]:
        if recipient.id in seen:
            continue
        seen.add(recipient.id)
        arbiter_ids.append(recipient.id)
        notif, ws_payload = await notifier.insert(
            session,
            recipient.id,
            NotificationType.deals,
            "Арбитраж",
            f"Сделка #{deal.id} передана в арбитраж: {reason}",
            {"deal_id": deal.id},
        )
        pending.append((notif, ws_payload))
    await session.commit()
    await _safe_dispatch(session, pending)
    await notifier.publish_deal_update(
        deal.id,
        [deal.buyer_id, deal.seller_id, *arbiter_ids],
        status=deal.status.value,
    )
    return deal


async def resolve_arbitration(
    session: AsyncSession,
    deal: Deal,
    admin: User,
    winner: str,
    note: str = "",
) -> Deal:
    if not (admin.is_admin or admin.is_arbiter):
        raise ValueError("Только администратор или арбитр может разрешать спор")
    if deal.status != DealStatus.arbitration:
        raise ValueError("Сделка не в статусе арбитража")
    if winner not in ("buyer", "seller"):
        raise ValueError("winner должен быть 'buyer' или 'seller'")
    if deal.currency_id is None or deal.amount is None:
        raise ValueError("У сделки не задана валюта")

    currency = await session.get(Currency, deal.currency_id)
    # V11-L-18 — explicit raise instead of ``assert``.
    if currency is None:
        raise ValueError("currency vanished")
    amt = quantize_money(Decimal(str(deal.amount)), currency.decimals)

    if winner == "buyer":
        # P10 — refund only the principal; commission stays on the
        # platform side. Same refund math as ``decline_deal`` /
        # ``accept_cancel``.
        await _refund_principal(session, deal.buyer_id, currency.id, amt)
        deal.status = DealStatus.resolved_for_buyer
    else:
        # P10 — seller receives full ``amount``; commission already
        # charged via the deposit invoice.
        await _release_to(session, deal.buyer_id, deal.seller_id, currency.id, amt, amt)
        deal.status = DealStatus.resolved_for_seller

    deal.arbitration_resolved_by = admin.id
    deal.arbitration_resolution = winner
    deal.arbitration_resolved_at = utcnow()
    deal.completed_at = utcnow()
    if note:
        deal.arbitration_reason = (
            f"{deal.arbitration_reason or ''}\n— Решение арбитра: {note}".strip()
        )

    winner_id = deal.buyer_id if winner == "buyer" else deal.seller_id
    loser_id = deal.seller_id if winner == "buyer" else deal.buyer_id

    # Counter bookkeeping: ``deals_failed`` for the losing side and
    # ``deals_success`` for the winning side. Voluntary cancellation
    # (``accept_cancel``) and inactivity sweeps do NOT bump these
    # counters because no participant "lost" — only an adversarial
    # arbitration outcome does. Single atomic UPDATE per side (same
    # pattern as ``accept_deal`` / ``confirm_deal``).
    await session.execute(
        update(User).where(User.id == loser_id).values(deals_failed=User.deals_failed + 1)
    )
    await session.execute(
        update(User).where(User.id == winner_id).values(deals_success=User.deals_success + 1)
    )

    # A9-M-2 — split-API: persist both notifications atomically, dispatch after commit.
    pending: list[tuple[Notification, dict[str, Any] | None]] = []
    winner_notif, winner_ws = await notifier.insert(
        session,
        winner_id,
        NotificationType.deals,
        "Спор решён в вашу пользу",
        f"Арбитр вынес решение по сделке #{deal.id}",
        {"deal_id": deal.id},
    )
    pending.append((winner_notif, winner_ws))
    loser_notif, loser_ws = await notifier.insert(
        session,
        loser_id,
        NotificationType.deals,
        "Спор решён не в вашу пользу",
        f"Арбитр вынес решение по сделке #{deal.id}",
        {"deal_id": deal.id},
    )
    pending.append((loser_notif, loser_ws))
    await session.commit()
    await _safe_dispatch(session, pending)
    await notifier.publish_deal_update(
        deal.id,
        [deal.buyer_id, deal.seller_id, admin.id],
        status=deal.status.value,
    )
    return deal


# ── Inactivity sweep ───────────────────────────────────


async def sweep_inactivity(session: AsyncSession) -> int:
    """Auto-cancel stale deals.

    * ``PENDING_CONFIRMATION`` older than ``inactivity_pending_confirmation_days``
      → ``CANCELLED_FOR_INACTIVITY`` and refund buyer.
    * ``PENDING_CANCELLATION`` older than ``inactivity_pending_cancellation_days``
      → ``CANCELLED`` and refund buyer.

    Returns the number of deals affected.
    """
    settings = await _settings(session)
    now = utcnow()
    pc_cutoff = now - timedelta(days=int(settings.inactivity_pending_confirmation_days))
    pcanc_cutoff = now - timedelta(days=int(settings.inactivity_pending_cancellation_days))

    affected = 0
    rows = (
        (
            await session.execute(
                select(Deal)
                .where(
                    or_(
                        (Deal.status == DealStatus.pending_confirmation)
                        & (Deal.created_at <= pc_cutoff),
                        (Deal.status == DealStatus.pending_cancellation)
                        & (Deal.cancellation_requested_at.is_not(None))
                        & (Deal.cancellation_requested_at <= pcanc_cutoff),
                    )
                )
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    # Hold the row locks for the whole sweep so a parallel sweeper or
    # admin force action can't double-process the same row. One commit
    # at the end releases them.
    #
    # Comment 32 (audit v10): insert notification rows BEFORE commit
    # (so they're atomic with the refund), but defer WS/DM dispatch
    # until AFTER commit — prevents broadcasting events for a
    # transaction that might still roll back.
    pending_dispatch: list[tuple[Notification, dict[str, Any] | None]] = []
    for deal in rows:
        if deal.currency_id is None or deal.amount is None:
            continue
        currency = await session.get(Currency, deal.currency_id)
        if currency is None:
            continue
        amt = quantize_money(Decimal(str(deal.amount)), currency.decimals)
        # P10 — refund only the principal; commission already charged
        # via the deposit invoice. Matches ``_refund_principal``
        # contract in the rest of the lifecycle.
        await _refund_principal(session, deal.buyer_id, currency.id, amt)
        target_status = (
            DealStatus.cancelled_for_inactivity
            if deal.status == DealStatus.pending_confirmation
            else DealStatus.cancelled
        )
        deal.status = target_status
        deal.completed_at = now
        for recipient_id in (deal.buyer_id, deal.seller_id):
            notif, ws_payload = await notifier.insert(
                session,
                recipient_id,
                NotificationType.deals,
                "Сделка отменена за неактивность",
                f"Сделка #{deal.id} автоматически закрыта.",
                {"deal_id": deal.id},
            )
            pending_dispatch.append((notif, ws_payload))
        affected += 1

    await session.commit()

    await _safe_dispatch(session, pending_dispatch, event="sweep_inactivity.dispatch.failed")
    for deal in rows:
        await notifier.publish_deal_update(
            deal.id, [deal.buyer_id, deal.seller_id], status=deal.status.value
        )
    return affected
