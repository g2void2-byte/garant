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
    AppSettings,
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
from ...sql_filters import escape_like_wildcards
from ...time_utils import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/withdrawals",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin", limit=600, window=60))],
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
        except ValueError:
            raise HTTPException(422, f"Неизвестный статус: {status}")
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
            stmt.order_by(WalletWithdrawal.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    # V5-B-9 — counters across the full table (independent of filters).
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

    # A9-M-2 — every branch below stages its user-facing notification
    # row before commit (atomic with the status flip + balance write)
    # and dispatches WS/DM after commit so a rolled-back decision
    # never leaks a "вывод выполнен" / "заявка отклонена" event for a
    # withdrawal whose state didn't actually change.
    pending: list[tuple[Notification, dict[str, Any] | None]] = []

    if body.action == "approve":
        if w.status != WalletWithdrawStatus.pending:
            raise HTTPException(409, "Заявка уже обработана")

        # Check auto-mode: if on, fire the CryptoBot Transfer and mark sent.
        app_row = (
            await session.execute(select(AppSettings).order_by(AppSettings.id).limit(1))
        ).scalar_one_or_none()
        auto = bool(app_row and app_row.auto_withdraw_enabled)
        transfer_id: int | None = None
        if (
            auto
            and app_settings_env.cryptobot_token
            and not (app_settings_env.cryptobot_token.startswith("000"))
        ):
            try:
                async with CryptoPay(
                    app_settings_env.cryptobot_token,
                    testnet=app_settings_env.cryptobot_testnet,
                ) as cp:
                    # V5-B-5 — ``spend_id=f"wd:{w.id}"`` is the
                    # idempotency key CryptoBot uses to dedupe
                    # ``transfer`` calls server-side. Per their docs:
                    # "Transfers with the same ``spend_id`` will be
                    # processed only once." That's how this auto-send
                    # path stays safe against a double click on the
                    # admin Approve button or a retry after a network
                    # timeout — both retries hit the same ``spend_id``
                    # and CryptoBot returns the already-processed
                    # transfer instead of paying out twice. The same
                    # key is used in
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
                raise HTTPException(502, f"Ошибка CryptoBot: {e}")

        if auto and transfer_id is not None:
            # Locked funds are gone for real now — drop them from the
            # user's locked column too.
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
                bal.locked = max(Decimal(0), Decimal(str(bal.locked)) - Decimal(str(w.amount)))
            w.status = WalletWithdrawStatus.sent
            w.processed_at = utcnow()
        else:
            w.status = WalletWithdrawStatus.approved
        w.admin_note = body.note or ""

        if currency and user and w.status == WalletWithdrawStatus.sent:
            notif, ws_payload = await notifier.insert(
                session,
                user.id,
                NotificationType.deposits,
                "Вывод выполнен",
                f"-{w.amount} {currency.code} отправлены на {w.address}",
                {"withdrawal_id": w.id},
            )
            pending.append((notif, ws_payload))

        await log_admin_action(
            session,
            actor=admin,
            action="withdrawal.approve" if not auto else "withdrawal.auto_send",
            target_type="withdrawal",
            target_id=w.id,
            reason=body.note,
            payload={
                "user_id": w.user_id,
                "currency": currency.code if currency else None,
                "amount": str(w.amount),
                "auto": auto,
                "cryptobot_transfer_id": transfer_id,
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
            bal.locked = max(Decimal(0), Decimal(str(bal.locked)) - Decimal(str(w.amount)))
            bal.amount = Decimal(str(bal.amount)) + Decimal(str(w.amount))
        w.status = WalletWithdrawStatus.rejected
        w.admin_note = body.note or ""
        w.processed_at = utcnow()
        # V5-B-6 — clear the cool-down timer on rejection. The
        # ``locked_until`` column tracks when funds become spendable
        # again after the 24h cool-down (set in
        # ``services_wallet.create_withdrawal``). On reject we just
        # restored ``bal.amount`` immediately above, so the cool-down
        # no longer applies — anything else is a UI lie: the frontend
        # surfaces ``locked_until`` to mean "your funds are locked
        # until X" and showing a future timestamp on a row whose funds
        # are already back in ``amount`` is at best confusing and at
        # worst makes the user think they were partially refunded.
        w.locked_until = None
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
            bal.locked = max(Decimal(0), Decimal(str(bal.locked)) - Decimal(str(w.amount)))
        w.status = WalletWithdrawStatus.sent
        w.admin_note = body.note or w.admin_note
        w.processed_at = utcnow()
        if currency and user:
            notif, ws_payload = await notifier.insert(
                session,
                user.id,
                NotificationType.deposits,
                "Вывод выполнен",
                f"-{w.amount} {currency.code} отправлены на {w.address}",
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
