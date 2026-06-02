"""``/api/admin/withdrawals`` — withdrawal queue with auto/manual modes.

Endpoints:

* ``GET /api/admin/withdrawals`` — list with status filter
  (``pending`` / ``approved`` / ``sent`` / ``rejected``). Counters
  for the top tab bar.
* ``POST /api/admin/withdrawals/:id/decide`` — approve / reject /
  ``mark_sent``. Reject returns the locked funds to the user; approve
  with ``auto_withdraw_enabled=True`` triggers a CryptoBot Transfer
  immediately (marking ``sent`` on success).

The CryptoBot transfer is keyed by ``spend_id = "wd:{id}"`` so
double-clicking approve cannot trigger two payouts — CryptoBot
deduplicates server-side.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select

from ... import notifier
from ...admin_audit import log_admin_action
from ...admin_guard import TotpUser
from ...config import settings as app_settings_env
from ...cryptopay import CryptoPay, CryptoPayError
from ...deps import AdminUser, SessionDep
from ...models import (
    Currency,
    Notification,
    NotificationType,
    User,
    UserBalance,
    WalletWithdrawal,
    WalletWithdrawStatus,
)
from ...money import quantize_money
from ...rate_limit import rate_limit
from ...schemas import (
    AdminWithdrawalDecisionIn,
    AdminWithdrawalListOut,
    AdminWithdrawalOut,
)
from ...services_ledger import record_balance_ledger
from ...services_wallet import (
    clear_withdrawal_auto_send_in_progress,
    is_cryptopay_configured,
    mark_withdrawal_auto_send_failed,
    mark_withdrawal_auto_send_in_progress,
    withdrawal_auto_send_in_progress,
)
from ...sql_filters import escape_like_wildcards
from ...time_utils import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/withdrawals",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin:withdrawals", limit=600, window=60))],
)


def _to_out(w: WalletWithdrawal, c: Currency | None, u: User | None) -> AdminWithdrawalOut:
    # H-2: quantise on output — same contract as the deposit / treasury
    # admin DTOs. ``ROUND_HALF_EVEN`` via ``quantize_money`` keeps the
    # withdrawal queue's wire format aligned with the currency's own
    # ``decimals``.
    decimals = c.decimals if c is not None else 8
    return AdminWithdrawalOut(
        id=w.id,
        user_id=w.user_id,
        username=u.username if u else None,
        display_name=u.display_name if u else "",
        currency_code=c.code if c else "",
        amount=quantize_money(w.amount, decimals),
        address=w.address,
        status=w.status.value,
        admin_note=w.admin_note,
        created_at=w.created_at,
        processed_at=w.processed_at,
    )


@router.get("", response_model=AdminWithdrawalListOut)
async def list_withdrawals(
    _admin: AdminUser,
    session: SessionDep,
    status: str | None = Query(None),
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    stmt = (
        select(WalletWithdrawal, Currency, User)
        .join(Currency, Currency.id == WalletWithdrawal.currency_id)
        .join(User, User.id == WalletWithdrawal.user_id)
    )
    if status:
        try:
            stmt = stmt.where(WalletWithdrawal.status == WalletWithdrawStatus(status))
        except ValueError as e:
            raise HTTPException(422, f"Неизвестный статус: {status}") from e
    if q:
        like = f"%{escape_like_wildcards(q)}%"
        stmt = stmt.where(
            or_(
                User.username.ilike(like, escape="\\"),
                User.display_name.ilike(like, escape="\\"),
            )
        )

    rows = (
        await session.execute(
            stmt.order_by(WalletWithdrawal.created_at.desc(), WalletWithdrawal.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    # counters across the full table (independent of filters).
    # Pre-fix this issued 4 separate ``SELECT id WHERE status=?`` round
    # trips and materialised every id in Python just to call ``len()``
    # on the list — O(N) network + memory per status, for 4 statuses,
    # on every page load. ``GROUP BY status`` returns one row per
    # status (4 rows total) in a single round trip; populate any
    # status that doesn't appear in the result with ``0`` so the
    # response shape is stable for the frontend tab bar.
    counter_rows = (
        await session.execute(
            select(WalletWithdrawal.status, func.count(WalletWithdrawal.id)).group_by(
                WalletWithdrawal.status
            )
        )
    ).all()
    counters: dict[str, int] = {s.value: 0 for s in WalletWithdrawStatus}
    for status_val, n in counter_rows:
        # ``status_val`` is a ``WalletWithdrawStatus`` enum when the
        # column type maps round-trip (default with SQLAlchemy's Enum
        # adapter); ``getattr(..., "value", str(...))`` is defensive
        # in case a driver returns the raw string.
        counters[getattr(status_val, "value", str(status_val))] = int(n)

    return AdminWithdrawalListOut(
        items=[_to_out(w, c, u) for w, c, u in rows],
        counters=counters,
    )


@router.post("/{withdrawal_id}/decide", response_model=AdminWithdrawalOut)
async def decide_withdrawal(
    withdrawal_id: int,
    body: AdminWithdrawalDecisionIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
):
    w = (
        await session.execute(
            select(WalletWithdrawal).where(WalletWithdrawal.id == withdrawal_id).with_for_update()
        )
    ).scalar_one_or_none()
    if w is None:
        raise HTTPException(404, "Заявка не найдена")

    currency = await session.get(Currency, w.currency_id)
    if not currency:
        raise HTTPException(404, "Валюта не найдена")
    user = await session.get(User, w.user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    if body.action in ("approve", "reject") and withdrawal_auto_send_in_progress(w):
        raise HTTPException(409, "Авто-отправка вывода уже выполняется")

    # A9-M-2 — every branch below stages its user-facing notification
    # row before commit (atomic with the status flip + balance write)
    # and dispatches WS/DM after commit so a rolled-back decision
    # never leaks a "вывод выполнен" / "заявка отклонена" event for a
    # withdrawal whose state didn't actually change.
    pending: list[tuple[Notification, dict[str, Any] | None]] = []

    if body.action == "approve":
        if w.status != WalletWithdrawStatus.pending:
            raise HTTPException(409, "Заявка уже обработана")

        # V14 — Approve always dispatches the payout via CryptoBot
        # Transfer when the token is configured (which is the only
        # supported deployment going forward). ``auto_withdraw_enabled``
        # now only controls whether the user-facing
        # ``services_wallet.create_withdrawal`` runs the Transfer at
        # request time or queues the row for admin review; in the
        # admin path the Approve button is always the trigger.
        if is_cryptopay_configured(app_settings_env.cryptobot_token):
            # 4.2 (HIGH) — two-phase commit so the row lock on
            # ``wallet_withdrawals`` is NOT held through the CryptoBot
            # HTTP roundtrip. Pre-fix the ``with_for_update()`` lock
            # was kept alive across ``cp.transfer(...)``, meaning a
            # slow / retrying CryptoBot upstream would block every
            # other admin / user query that touches the same row
            # (repeat Approve clicks, the user's wallet polling)
            # for the duration of the network call. ``spend_id``
            # idempotency (see the comment on the ``cp.transfer``
            # call below) still protects against duplicate payouts
            # if two admins race after the lock is released.
            #
            # Phase 1: mark ``approved`` (intermediate state — same
            # state the non-auto branch terminates in) and COMMIT,
            # which drops the row lock. The admin-action audit row
            # is deliberately written in Phase 2 alongside the
            # CryptoBot ``transfer_id`` so the audit log records the
            # outcome, not just the intent. If the worker crashes
            # between Phase 1 and Phase 2 the row stays at
            # ``approved`` with no audit row, and a manual operator
            # can pick it up with the existing ``mark_sent`` path
            # (CryptoBot will dedupe via ``spend_id``).
            w.status = WalletWithdrawStatus.approved
            w.admin_note = mark_withdrawal_auto_send_in_progress(body.note or "")
            await session.commit()

            # Phase 2: CryptoBot HTTP call WITHOUT any DB locks held.
            transfer_id: int | None = None
            try:
                async with CryptoPay(
                    app_settings_env.cryptobot_token,
                    testnet=app_settings_env.cryptobot_testnet,
                ) as cp:
                    # ``spend_id=f"wd:{w.id}"`` is the idempotency key
                    # CryptoBot uses to dedupe ``transfer`` calls
                    # server-side. Per their docs: "Transfers with the
                    # same ``spend_id`` will be processed only once."
                    # That's how this auto-send path stays safe
                    # against a double click on the admin Approve
                    # button, a retry after a network timeout, OR a
                    # second admin's race after Phase 1 commits and
                    # releases the lock — every retry hits the same
                    # ``spend_id`` and CryptoBot returns the
                    # already-processed transfer instead of paying
                    # out twice. The same key is used in
                    # ``services_wallet.create_withdrawal`` for the
                    # user-facing auto-mode path; both share the
                    # ``w.id`` namespace because each withdrawal has
                    # exactly one ``WalletWithdrawal`` row.
                    tr = await cp.transfer(
                        user_id=user.tg_user_id,
                        asset=currency.code,
                        amount=str(w.amount),
                        spend_id=f"wd:{w.id}",
                        comment=f"Garant withdrawal #{w.id}",
                    )
                transfer_id = tr.transfer_id
            except CryptoPayError as e:
                # V11-L-15 — surface withdrawal/user/currency context
                # as structured log fields so the JSON-logger downstream
                # (Loki/Sentry) can query by user/currency without
                # regexing the human message body.
                logger.error(
                    "withdrawal #%s CryptoBot transfer failed: %s",
                    w.id,
                    e,
                    extra={
                        "event": "cryptobot.admin_decide_transfer.failed",
                        "withdrawal_id": w.id,
                        "user_id": w.user_id,
                        "currency": currency.code if currency else None,
                        "amount": str(w.amount),
                        "actor_id": admin.id,
                    },
                )
                # We DO NOT roll the status back to ``pending`` /
                # release ``balance.locked`` here: the CryptoBot
                # error may mask a successful transfer (network
                # blip on the response), and releasing the locked
                # funds would let the user re-withdraw them while
                # the upstream payout is in flight. Idempotency via
                # ``spend_id`` only protects retries while the row
                # is still ``approved``; if we returned to
                # ``pending`` and the user spent the freed balance,
                # the next approve attempt would observe the
                # already-paid transfer and silently double-spend.
                #
                # Instead, re-lock the row briefly, stamp the
                # error onto ``admin_note`` so the admin UI's
                # existing column makes the failure visible at a
                # glance, and audit the failure. An operator now
                # has two recovery paths:
                #   * ``mark_sent`` — funds did arrive; CryptoBot
                #     dedupes on ``spend_id`` for any later retry.
                #   * ``reject`` — funds did NOT arrive; this
                #     branch releases ``balance.locked`` back to
                #     ``balance.amount`` (see the reject branch).
                w_locked = (
                    await session.execute(
                        select(WalletWithdrawal)
                        .where(WalletWithdrawal.id == w.id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).scalar_one_or_none()
                if w_locked is not None:
                    w_locked.admin_note = mark_withdrawal_auto_send_failed(
                        w_locked.admin_note,
                        e,
                    )
                await log_admin_action(
                    session,
                    actor=admin,
                    action="withdrawal.auto_send_failed",
                    target_type="withdrawal",
                    target_id=w.id,
                    reason=body.note,
                    payload={
                        "user_id": w.user_id,
                        "currency": currency.code if currency else None,
                        "amount": str(w.amount),
                        "auto": True,
                        "error": str(e),
                    },
                    request=request,
                )
                await session.commit()
                raise HTTPException(502, f"Ошибка CryptoBot: {e}") from e

            # Phase 3: re-lock the row, mark ``sent``, decrement
            # ``balance.locked``, stage the notification, write the
            # audit row, and commit. ``with_for_update()`` is taken
            # only for this short, network-free critical section.
            w_locked = (
                await session.execute(
                    select(WalletWithdrawal)
                    .where(WalletWithdrawal.id == withdrawal_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if w_locked is None:
                raise HTTPException(404, "Заявка не найдена")
            if w_locked.status not in (
                WalletWithdrawStatus.approved,
                WalletWithdrawStatus.sent,
            ):
                # Status changed under us (e.g. someone rejected
                # before Phase 3 acquired the lock). CryptoBot has
                # already shipped the funds — bail loudly so the
                # operator notices the inconsistency.
                logger.error(
                    "withdrawal #%s status changed under auto-send Phase 3: %s",
                    w.id,
                    w_locked.status.value,
                    extra={
                        "event": "cryptobot.admin_decide_transfer.race",
                        "withdrawal_id": w.id,
                        "observed_status": w_locked.status.value,
                        "cryptobot_transfer_id": transfer_id,
                    },
                )
                raise HTTPException(409, "Заявка уже обработана")
            if w_locked.status == WalletWithdrawStatus.sent:
                # Already marked sent (idempotent replay of Phase 3
                # after a crash). Return the existing row.
                w = w_locked
            else:
                bal = (
                    await session.execute(
                        select(UserBalance)
                        .where(
                            UserBalance.user_id == w_locked.user_id,
                            UserBalance.currency_id == w_locked.currency_id,
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if bal is not None:
                    before_amount = Decimal(str(bal.amount))
                    before_locked = Decimal(str(bal.locked))
                    bal.locked = max(
                        Decimal(0),
                        Decimal(str(bal.locked)) - Decimal(str(w_locked.amount)),
                    )
                    record_balance_ledger(
                        session,
                        bal,
                        before_amount=before_amount,
                        before_locked=before_locked,
                        event_type="withdrawal.sent",
                        source_type="withdrawal",
                        source_id=w_locked.id,
                        provider="cryptobot",
                        provider_event_id=str(transfer_id) if transfer_id is not None else None,
                    )
                w_locked.status = WalletWithdrawStatus.sent
                w_locked.admin_note = clear_withdrawal_auto_send_in_progress(
                    w_locked.admin_note,
                )
                w_locked.processed_at = utcnow()
                _dst = w_locked.address or "в @CryptoBot"
                notif, ws_payload = await notifier.insert(
                    session,
                    user.id,
                    NotificationType.deposits,
                    "Вывод выполнен",
                    f"-{w_locked.amount} {currency.code} отправлены на {_dst}",
                    {"withdrawal_id": w_locked.id},
                )
                pending.append((notif, ws_payload))
                await log_admin_action(
                    session,
                    actor=admin,
                    action="withdrawal.auto_send",
                    target_type="withdrawal",
                    target_id=w_locked.id,
                    reason=body.note,
                    payload={
                        "user_id": w_locked.user_id,
                        "currency": currency.code if currency else None,
                        "amount": str(w_locked.amount),
                        "auto": True,
                        "cryptobot_transfer_id": transfer_id,
                    },
                    request=request,
                )
                w = w_locked
        else:
            # No CryptoBot token configured — there is no automated
            # payout channel, the admin must finish the transfer
            # manually in @CryptoBot and then click "mark sent". Stay
            # in ``approved`` and log it loudly so ops notice the
            # missing token rather than only finding out when users
            # complain about a stuck queue.
            logger.warning(
                "withdrawal.approve: CryptoBot token missing — manual mark_sent required",
                extra={
                    "event": "withdrawal.auto_disabled.missing_token",
                    "withdrawal_id": w.id,
                    "user_id": w.user_id,
                    "currency": currency.code if currency else None,
                    "amount": str(w.amount),
                    "actor_id": admin.id,
                },
            )
            w.status = WalletWithdrawStatus.approved
            w.admin_note = body.note or ""
            await log_admin_action(
                session,
                actor=admin,
                action="withdrawal.approve",
                target_type="withdrawal",
                target_id=w.id,
                reason=body.note,
                payload={
                    "user_id": w.user_id,
                    "currency": currency.code if currency else None,
                    "amount": str(w.amount),
                    "auto": False,
                    "cryptobot_transfer_id": None,
                },
                request=request,
            )

    elif body.action == "reject":
        if w.status not in (
            WalletWithdrawStatus.pending,
            WalletWithdrawStatus.approved,
        ):
            raise HTTPException(409, "Заявка уже обработана")
        bal = (
            await session.execute(
                select(UserBalance)
                .where(
                    UserBalance.user_id == w.user_id,
                    UserBalance.currency_id == w.currency_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if bal is not None:
            before_amount = Decimal(str(bal.amount))
            before_locked = Decimal(str(bal.locked))
            bal.locked = max(Decimal(0), Decimal(str(bal.locked)) - Decimal(str(w.amount)))
            bal.amount = Decimal(str(bal.amount)) + Decimal(str(w.amount))
            record_balance_ledger(
                session,
                bal,
                before_amount=before_amount,
                before_locked=before_locked,
                event_type="withdrawal.reject",
                source_type="withdrawal",
                source_id=w.id,
                meta={"admin_id": admin.id},
            )
        w.status = WalletWithdrawStatus.rejected
        w.admin_note = body.note or ""
        w.processed_at = utcnow()
        if currency and user:
            notif, ws_payload = await notifier.insert(
                session,
                user.id,
                NotificationType.deposits,
                "Заявка на вывод отклонена",
                f"{w.amount} {currency.code} возвращены на баланс. {body.note or ''}".strip(),
                {"withdrawal_id": w.id},
            )
            pending.append((notif, ws_payload))
        await log_admin_action(
            session,
            actor=admin,
            action="withdrawal.reject",
            target_type="withdrawal",
            target_id=w.id,
            reason=body.note,
            payload={
                "user_id": w.user_id,
                "currency": currency.code if currency else None,
                "amount": str(w.amount),
            },
            request=request,
        )

    elif body.action == "mark_sent":
        if w.status != WalletWithdrawStatus.approved:
            raise HTTPException(409, "Можно отметить отправленным только одобренную заявку")
        bal = (
            await session.execute(
                select(UserBalance)
                .where(
                    UserBalance.user_id == w.user_id,
                    UserBalance.currency_id == w.currency_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if bal is not None:
            before_amount = Decimal(str(bal.amount))
            before_locked = Decimal(str(bal.locked))
            bal.locked = max(Decimal(0), Decimal(str(bal.locked)) - Decimal(str(w.amount)))
            record_balance_ledger(
                session,
                bal,
                before_amount=before_amount,
                before_locked=before_locked,
                event_type="withdrawal.sent",
                source_type="withdrawal",
                source_id=w.id,
                meta={"admin_id": admin.id, "manual": True},
            )
        w.status = WalletWithdrawStatus.sent
        w.admin_note = clear_withdrawal_auto_send_in_progress(body.note or w.admin_note)
        w.processed_at = utcnow()
        if currency and user:
            _dst = w.address or "в @CryptoBot"
            notif, ws_payload = await notifier.insert(
                session,
                user.id,
                NotificationType.deposits,
                "Вывод выполнен",
                f"-{w.amount} {currency.code} отправлены на {_dst}",
                {"withdrawal_id": w.id},
            )
            pending.append((notif, ws_payload))
        await log_admin_action(
            session,
            actor=admin,
            action="withdrawal.mark_sent",
            target_type="withdrawal",
            target_id=w.id,
            reason=body.note,
            payload={
                "user_id": w.user_id,
                "currency": currency.code if currency else None,
                "amount": str(w.amount),
            },
            request=request,
        )

    await session.commit()
    for notif, ws_payload in pending:
        try:
            await notifier.dispatch_after_commit(session, notif, ws_payload)
        except Exception:
            logger.exception(
                "decide_withdrawal: post-commit dispatch failed for notif id=%s",
                notif.id,
                extra={
                    "event": "decide_withdrawal.dispatch.failed",
                    "notif_id": notif.id,
                },
            )
    return _to_out(w, currency, user)
