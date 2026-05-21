"""``/api/admin/treasury`` — commission accumulator + payouts.

Computed dynamically from completed deals minus successful treasury
withdrawals — there is no separate "treasury balance" column. This
avoids the bookkeeping consistency risk of double-writing on every
deal completion.

Endpoints:

* ``GET /api/admin/treasury`` — per-currency balances (accrued /
  withdrawn / available) + total withdrawal count.
* ``GET /api/admin/treasury/withdrawals`` — list of past withdrawals.
* ``POST /api/admin/treasury/withdraw`` — 2FA-gated payout to an
  external address. Requires ``confirm=true`` (double-confirm) and a
  valid TOTP code in the ``X-Totp-Code`` header.
* ``POST /api/admin/treasury/{withdrawal_id}/mark_sent`` — manual
  reconciliation: flip a stuck ``pending`` row to ``sent`` after the
  operator verified the CryptoBot transfer succeeded out-of-band
  (Phase 2 OK, Phase 3 crashed). Mirrors the ``mark_sent`` action on
  ``/api/admin/withdrawals``.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select, text

from ...admin_audit import log_admin_action
from ...admin_guard import TotpUser
from ...config import settings as app_settings_env
from ...cryptopay import CryptoPay, CryptoPayError
from ...deps import AdminUser, SessionDep
from ...models import Currency, Deal, DealStatus, PayCommission, TreasuryWithdrawal
from ...money import quantize_money
from ...rate_limit import rate_limit
from ...schemas import (
    AdminTreasuryBalanceOut,
    AdminTreasuryMarkSentIn,
    AdminTreasuryOverviewOut,
    AdminTreasuryWithdrawIn,
    AdminTreasuryWithdrawOut,
)
from ...services_wallet import is_cryptopay_configured

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/treasury",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin:treasury", limit=600, window=60))],
)


# Terminal deal statuses considered when summing accrued commission.
# Per spec, commission is charged once a deal reaches a terminal
# status — but only in the paths where money actually changed hands
# on the commission line (see ``_accrued_by_currency``). Only the
# explicit admin "delete" path returns the full locked pot to the
# buyer — and a deleted deal is removed from this query because the
# row no longer exists.
_DONE_STATUSES = (
    DealStatus.completed,
    DealStatus.cancelled,
    DealStatus.cancelled_for_inactivity,
    DealStatus.resolved_for_buyer,
    DealStatus.resolved_for_seller,
)

# Statuses where the seller actually received the payout — i.e. the
# commission was deducted from that payout regardless of who agreed
# to pay it. See Audit H1 below for the ``pay_commission`` interplay.
_SELLER_PAID_STATUSES = (
    DealStatus.completed,
    DealStatus.resolved_for_seller,
)


async def _accrued_by_currency(session) -> dict[int, Decimal]:
    """Sum commission *actually collected* on every terminal deal.

    Audit H1 — a deal where ``pay_commission == seller`` only locks
    ``amount`` (not ``amount + commission``) from the buyer; the
    commission is taken from the seller's payout at
    ``finish_deal`` / ``resolved_for_seller`` time. When such a deal
    finishes *not* in the seller's favour (cancellation, inactivity
    sweep, arbitration ruled for the buyer) the buyer is refunded the
    full locked ``amount`` and the seller never pays anything — so
    no real commission was collected, even though ``Deal.commission_amount``
    is still a non-zero theoretical figure on the row.

    The previous ``SUM(commission_amount) WHERE status IN _DONE_STATUSES``
    rolled those phantom amounts into ``accrued`` anyway, which let an
    admin ``POST /api/admin/treasury/withdraw`` move funds out of the
    treasury that never landed there — a direct accounting deficit
    against the real per-user wallet balances. The fix filters the
    commission so it counts only when (a) the seller was paid (any
    ``pay_commission`` setting) or (b) the buyer paid the commission
    upfront and it stayed with the platform on refund.
    """
    rows = (
        await session.execute(
            select(Deal.currency_id, func.coalesce(func.sum(Deal.commission_amount), 0))
            .where(
                Deal.status.in_(_DONE_STATUSES),
                or_(
                    Deal.status.in_(_SELLER_PAID_STATUSES),
                    Deal.pay_commission == PayCommission.buyer,
                ),
            )
            .group_by(Deal.currency_id)
        )
    ).all()
    return {cid: Decimal(str(amount or 0)) for cid, amount in rows if cid is not None}


# Statuses that count against the available balance. ``pending`` is
# included so a row in-flight (its CryptoBot transfer hasn't returned
# yet) can't be double-spent by another admin running concurrently.
# Only ``failed`` is excluded — those rows are explicit "no money
# left the platform" markers.
_OUTSTANDING_STATUSES = ("pending", "sent")


async def _withdrawn_by_currency(session) -> dict[int, Decimal]:
    """Sum of withdrawals that have already left or are leaving."""
    rows = (
        await session.execute(
            select(
                TreasuryWithdrawal.currency_id,
                func.coalesce(func.sum(TreasuryWithdrawal.amount), 0),
            )
            .where(TreasuryWithdrawal.status.in_(_OUTSTANDING_STATUSES))
            .group_by(TreasuryWithdrawal.currency_id)
        )
    ).all()
    return {cid: Decimal(str(amount or 0)) for cid, amount in rows}


# Namespace key for ``pg_advisory_xact_lock(key1, key2)``. Combining
# this constant with ``currency_id`` means concurrent treasury writes
# on the same currency serialize, while writes on different
# currencies (or on unrelated tables) don't contend.
_TREASURY_LOCK_NS = 0x74727377  # "trsw"


async def _lock_treasury(session, currency_id: int) -> None:
    """Take a per-currency Postgres advisory lock for this transaction.

    Released automatically when the transaction commits or rolls back.
    Prevents two concurrent ``POST /withdraw`` calls on the same
    currency from both passing the ``available`` guard.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :cid)"),
        {"ns": _TREASURY_LOCK_NS, "cid": int(currency_id)},
    )


@router.get("", response_model=AdminTreasuryOverviewOut)
async def treasury_overview(_admin: AdminUser, session: SessionDep):
    currencies = (
        (await session.execute(select(Currency).order_by(Currency.sort_order))).scalars().all()
    )
    accrued = await _accrued_by_currency(session)
    withdrawn = await _withdrawn_by_currency(session)
    total_count = (
        await session.execute(select(func.count()).select_from(TreasuryWithdrawal))
    ).scalar_one()

    balances = []
    for c in currencies:
        # H-2: quantise on output so the wire format never carries
        # more fractional digits than the currency itself supports.
        # ``ROUND_HALF_EVEN`` via ``quantize_money`` keeps the
        # ``available`` projection consistent with the underlying
        # ``accrued - withdrawn`` arithmetic.
        a = quantize_money(accrued.get(c.id, Decimal(0)), c.decimals)
        w = quantize_money(withdrawn.get(c.id, Decimal(0)), c.decimals)
        balances.append(
            AdminTreasuryBalanceOut(
                currency_id=c.id,
                currency_code=c.code,
                currency_name=c.name,
                decimals=c.decimals,
                accrued=a,
                withdrawn=w,
                available=quantize_money(a - w, c.decimals),
            )
        )
    return AdminTreasuryOverviewOut(balances=balances, total_withdrawals=int(total_count))


def _withdrawal_to_out(w: TreasuryWithdrawal, c: Currency | None) -> AdminTreasuryWithdrawOut:
    # H-2: ``w.amount`` comes from a ``Numeric(28, 8)`` column;
    # quantise to the currency's ``decimals`` on the way out so the
    # admin UI never sees more fractional digits than the asset
    # itself uses. Falls back to the canonical scale (8) if the
    # currency row was purged out from under us — the wider shape
    # cannot drop information.
    decimals = c.decimals if c is not None else 8
    return AdminTreasuryWithdrawOut(
        id=w.id,
        actor_id=w.actor_id,
        currency_code=c.code if c else "",
        amount=quantize_money(w.amount, decimals),
        address=w.address,
        status=w.status,
        note=w.note,
        cryptobot_transfer_id=w.cryptobot_transfer_id,
        created_at=w.created_at,
    )


@router.get("/withdrawals", response_model=list[AdminTreasuryWithdrawOut])
async def list_treasury_withdrawals(
    _admin: AdminUser,
    session: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    # Audit §5.11 — optional status filter so the admin panel can
    # surface "pending payouts" / "failed retries" without paginating
    # through the full history. Whitelisted against the closed set
    # the writer side actually emits (``treasury_withdraw`` sets
    # ``pending`` on insert and either ``sent`` on Phase 3 success
    # or ``failed`` on Phase 2 error; ``treasury_mark_sent`` flips
    # ``pending`` → ``sent``) so an unknown value 400s instead of
    # silently returning everything.
    status: Literal["pending", "sent", "failed"] | None = Query(None),
):
    stmt = select(TreasuryWithdrawal, Currency).join(
        Currency, Currency.id == TreasuryWithdrawal.currency_id
    )
    if status is not None:
        stmt = stmt.where(TreasuryWithdrawal.status == status)
    rows = (
        await session.execute(
            stmt.order_by(TreasuryWithdrawal.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [_withdrawal_to_out(w, c) for w, c in rows]


@router.post("/withdraw", response_model=AdminTreasuryWithdrawOut)
async def treasury_withdraw(
    body: AdminTreasuryWithdrawIn,
    admin: TotpUser,
    request: Request,
    session: SessionDep,
):
    """Withdraw accumulated commission to an external Telegram user_id.

    Guards:
      * 2FA via ``X-Totp-Code`` header.
      * ``confirm=true`` — explicit second click.
      * Per-currency advisory lock taken only for the ``available``
        check + ``pending`` row insert. The lock is **released by
        the commit at the end of Phase 1**, so the CryptoBot HTTP
        roundtrip in Phase 2 is not blocking any other admin or any
        other ``available`` calculation. A second admin attempting
        a payout on the same currency while Phase 2 is in flight
        sees the ``pending`` row counted in ``_OUTSTANDING_STATUSES``
        and gets a "недостаточно комиссии" 400 — not a queued lock
        wait.
      * Insert a ``pending`` row before the CryptoBot call so the
        ``spend_id`` is deterministic (``treas:{row.id}``). A retry
        from the admin produces a fresh row with its own id and its
        own spend_id; an in-flight crash leaves the ``pending`` row
        counted against ``available`` so the balance can't be
        double-spent until someone reconciles.

    Audit follow-up (2026-05-19) — T1/T2:

      * T1: ``body.address`` is validated to be a digit-only Telegram
        ``user_id`` by ``AdminTreasuryWithdrawIn._address_ok``, so the
        pre-fix ``int(body.address) if body.address.isdigit() else
        admin.tg_user_id`` silent self-payout fallback is gone.
      * T2: the per-currency advisory lock is no longer held across
        the CryptoBot HTTP call. See the three-phase comment above.
    """
    if not body.confirm:
        raise HTTPException(400, "Подтверждение не получено (confirm=false)")

    # Comment 48 (audit v9): without a configured CryptoBot token there is
    # no way to actually move funds, so the post-2026 codepath silently
    # marked the row ``status="sent"`` and committed — making the
    # accounting ledger believe a payout had been made while no transfer
    # ever happened. Reject early with 503 instead, before we touch the
    # DB or burn the per-currency advisory lock, so misconfigured envs
    # fail loudly rather than silently double-spending the treasury.
    if not is_cryptopay_configured(app_settings_env.cryptobot_token):
        raise HTTPException(503, "CryptoBot не настроен: вывод казны недоступен")

    currency = (
        await session.execute(select(Currency).where(Currency.code == body.currency_code))
    ).scalar_one_or_none()
    if currency is None:
        raise HTTPException(404, f"Валюта {body.currency_code} не найдена")

    # ─── Phase 1: take advisory lock, check ``available``, INSERT
    #             ``pending`` row, commit (releases the lock).
    await _lock_treasury(session, currency.id)

    accrued = await _accrued_by_currency(session)
    withdrawn = await _withdrawn_by_currency(session)
    available = accrued.get(currency.id, Decimal(0)) - withdrawn.get(currency.id, Decimal(0))
    if Decimal(str(body.amount)) > available:
        raise HTTPException(400, f"Недостаточно комиссии: доступно {available} {currency.code}")

    # ``int(body.address)`` is safe because ``_address_ok`` guarantees
    # the string is digit-only and inside the int64 range.
    target_user_id = int(body.address)

    row = TreasuryWithdrawal(
        actor_id=admin.id,
        currency_id=currency.id,
        amount=body.amount,
        address=body.address,
        status="pending",
        note=body.note or "",
    )
    session.add(row)
    await session.flush()
    row_id = row.id
    currency_id = currency.id
    currency_code = currency.code
    await session.commit()

    # ─── Phase 2: CryptoBot HTTP call WITHOUT any DB locks held.
    # ``spend_id=f"treas:{row_id}"`` is the idempotency key CryptoBot
    # uses to dedupe ``transfer`` calls server-side: a Phase 3 retry
    # after a crash hits the same key and CryptoBot returns the
    # already-processed transfer instead of paying out twice.
    transfer_id: int | None = None
    transfer_error: CryptoPayError | None = None
    try:
        async with CryptoPay(
            app_settings_env.cryptobot_token,
            testnet=app_settings_env.cryptobot_testnet,
        ) as cp:
            tr = await cp.transfer(
                user_id=target_user_id,
                asset=currency_code,
                amount=str(body.amount),
                spend_id=f"treas:{row_id}",
                comment="Garant treasury withdrawal",
            )
        transfer_id = tr.transfer_id
    except CryptoPayError as e:
        transfer_error = e
        # V11-L-15 — structured-logging context so the JSON-logger
        # downstream surfaces actor/currency/amount as queryable
        # fields rather than substrings of the message.
        logger.error(
            "treasury withdraw failed: %s",
            e,
            extra={
                "event": "cryptobot.treasury_withdraw.failed",
                "treasury_withdrawal_id": row_id,
                "actor_id": admin.id,
                "currency": currency_code,
                "amount": str(body.amount),
            },
        )

    # ─── Phase 3: reload the row, flip ``sent``/``failed``, write
    #             the audit row, commit. No long-lived locks held;
    #             advisory lock is no longer needed because the row
    #             is keyed by ``id`` and we just update its status.
    row_locked = (
        await session.execute(
            select(TreasuryWithdrawal).where(TreasuryWithdrawal.id == row_id).with_for_update()
        )
    ).scalar_one_or_none()
    if row_locked is None:
        # Phase 1 row vanished — shouldn't happen, but treat as a hard
        # error so the operator notices. If CryptoBot already
        # processed the transfer, the funds are gone; the operator's
        # only recourse is reconciliation against CryptoBot's
        # transfer history. ``spend_id`` makes that lookup possible.
        raise HTTPException(500, "Treasury row исчез между Phase 1 и Phase 3")

    if transfer_error is not None:
        row_locked.status = "failed"
        row_locked.note = (row_locked.note or "") + f"\nfailed: {transfer_error}"
        await log_admin_action(
            session,
            actor=admin,
            action="treasury.withdraw_failed",
            target_type="treasury",
            target_id=row_id,
            reason=body.note,
            payload={
                "currency": currency_code,
                "amount": str(body.amount),
                "address": body.address,
                "error": str(transfer_error),
            },
            request=request,
        )
        await session.commit()
        raise HTTPException(502, f"Ошибка CryptoBot: {transfer_error}") from transfer_error

    row_locked.status = "sent"
    row_locked.cryptobot_transfer_id = str(transfer_id) if transfer_id is not None else None

    await log_admin_action(
        session,
        actor=admin,
        action="treasury.withdraw",
        target_type="treasury",
        target_id=row_id,
        reason=body.note,
        payload={
            "currency": currency_code,
            "amount": str(body.amount),
            "address": body.address,
            "cryptobot_transfer_id": transfer_id,
        },
        request=request,
    )
    await session.commit()

    currency_row = await session.get(Currency, currency_id)
    return _withdrawal_to_out(row_locked, currency_row)


@router.post("/{withdrawal_id}/mark_sent", response_model=AdminTreasuryWithdrawOut)
async def treasury_mark_sent(
    withdrawal_id: int,
    body: AdminTreasuryMarkSentIn,
    admin: TotpUser,
    request: Request,
    session: SessionDep,
):
    """Manually flip a stuck ``pending`` treasury row to ``sent``.

    Recovery path for the Phase 2 → Phase 3 gap in
    :func:`treasury_withdraw`: CryptoBot processed the transfer, but the
    final ``commit()`` never landed (network blip / crash), so the row
    is still ``pending`` and counted against ``available``. The operator
    verifies the transfer on CryptoBot's side (``spend_id=treas:{id}``
    or the dashboard), then calls this endpoint to advance the row.

    Guards:
      * 2FA via ``X-Totp-Code`` header.
      * ``confirm=true`` — explicit second click.
      * Row must be in ``pending``: ``sent`` rows are idempotent
        no-ops (we'd otherwise log duplicate audit rows), ``failed``
        rows are deliberately terminal and must be re-issued as a
        fresh withdrawal if the operator wants to retry.
      * ``with_for_update()`` row lock during the flip so a concurrent
        Phase 3 retry of the original ``treasury_withdraw`` (e.g. from
        a delayed-but-not-dead async task) doesn't race us.

    There is **no** new CryptoBot HTTP call here — by contract the
    transfer already happened. We only record what the operator
    observed.
    """
    if not body.confirm:
        raise HTTPException(400, "Подтверждение не получено (confirm=false)")

    row = (
        await session.execute(
            select(TreasuryWithdrawal)
            .where(TreasuryWithdrawal.id == withdrawal_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Запись о выводе казны не найдена")
    if row.status != "pending":
        # ``sent`` → already reconciled; ``failed`` → terminal, retry
        # is a new withdrawal. 409 mirrors the wallet-withdrawal
        # mark_sent handler.
        raise HTTPException(409, "Отметить отправленным можно только pending-запись")

    currency = await session.get(Currency, row.currency_id)
    currency_code = currency.code if currency else ""

    row.status = "sent"
    if body.cryptobot_transfer_id is not None:
        row.cryptobot_transfer_id = body.cryptobot_transfer_id
    if body.note:
        row.note = (row.note + "\n" if row.note else "") + f"mark_sent: {body.note}"

    await log_admin_action(
        session,
        actor=admin,
        action="treasury.mark_sent",
        target_type="treasury",
        target_id=row.id,
        reason=body.note,
        payload={
            "currency": currency_code,
            "amount": str(row.amount),
            "address": row.address,
            "cryptobot_transfer_id": body.cryptobot_transfer_id or row.cryptobot_transfer_id,
        },
        request=request,
    )
    await session.commit()

    return _withdrawal_to_out(row, currency)
