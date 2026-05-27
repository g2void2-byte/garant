"""HTTP endpoints for PIN-code authentication."""

from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..bot.notify import send_dm
from ..config import settings
from ..deps import CurrentUser, SessionDep
from ..models import AppSettings, Currency, User, UserBalance
from ..pin import (
    generate_reset_code,
    hash_pin,
    hash_reset_code,
    is_pin_format_valid,
    is_pin_too_common,
    issue_session_token,
    verify_pin,
    verify_reset_code,
)
from ..rate_limit import RLPin
from ..services_wallet import lock_user_balance
from ..time_utils import utcnow


async def _lock_user_for_pin(session: AsyncSession, user: User) -> User:
    """Re-load ``user`` with ``SELECT … FOR UPDATE`` so the
    ``pin_attempts`` / ``pin_reset_*`` read-modify-write below cannot
    race with a parallel call.

    ``CurrentUser`` loads the row without a lock, so two simultaneous
    wrong-PIN requests would both observe the pre-increment value
    and the commits would last-writer-wins, losing one increment
    and effectively doubling the attacker's allowed attempts before
    lockout. The row lock is held until the surrounding transaction
    commits or rolls back, which is exactly the window we need.

    ``populate_existing=True`` ensures the ORM-managed instance
    reflects the row data held under the lock (not a stale snapshot
    from the earlier unlocked load in ``get_current_user``).
    """
    locked = (
        await session.execute(
            select(User)
            .where(User.id == user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if locked is None:  # pragma: no cover — user just authed
        raise HTTPException(401, "Пользователь не найден")
    return locked

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/pin", tags=["pin"])


# ── DTO ────────────────────────────────────────────────


class PinStatusOut(BaseModel):
    has_pin: bool
    attempts_left: int
    locked_until: datetime | None
    max_attempts: int
    session_ttl_seconds: int


class PinSetupIn(BaseModel):
    pin: str = Field(..., min_length=4, max_length=4)


class PinCheckIn(BaseModel):
    pin: str = Field(..., min_length=4, max_length=4)


class PinChangeIn(BaseModel):
    old_pin: str = Field(..., min_length=4, max_length=4)
    new_pin: str = Field(..., min_length=4, max_length=4)


class PinResetConfirmIn(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)
    new_pin: str = Field(..., min_length=4, max_length=4)


class PinTokenOut(BaseModel):
    token: str
    expires_at: datetime


class PinResetRequestOut(BaseModel):
    delivered: bool
    expires_at: datetime


class PinResetPriceOut(BaseModel):
    """Public info shown in the "Забыли PIN" paywall modal.

    ``price`` and ``currency_code`` describe the configured USD price
    (admin-editable via ``AppSettings.pin_reset_price_usd``).
    ``user_balance`` is the user's USD-balance (``UserBalance.amount``
    for the USD ``Currency`` row) so the frontend can decide whether
    to enable the "Оплатить с баланса" button or show a "not enough"
    fallback. Falls back to 0 when the user has no USD row yet.
    """

    price: Decimal
    currency_code: str
    user_balance: Decimal
    can_afford: bool


class PinResetPaidOut(BaseModel):
    """Result of a paid PIN-reset: the reset code was just sent."""

    delivered: bool
    expires_at: datetime
    charged: Decimal
    currency_code: str


# ── Helpers ────────────────────────────────────────────


def _now() -> datetime:
    # Tz-naive UTC to match ``DateTime`` columns in the DB. Postgres
    # rejects tz-aware values written to ``TIMESTAMP WITHOUT TIME ZONE``.
    return utcnow()


def _is_locked(user) -> bool:
    if user.pin_locked_until is None:
        return False
    return user.pin_locked_until > _now()


def _attempts_left(user) -> int:
    return max(0, settings.pin_max_attempts - (user.pin_attempts or 0))


def _ensure_format(pin: str) -> None:
    """Reject obviously-malformed PINs (non-digit, wrong length).

    must be called BEFORE :func:`_is_locked`. The
    invariant is that a malformed payload returns 400 (a client
    bug) regardless of lock state; otherwise a locked user would
    see 423 even when their request body was never going to be
    accepted, which conflates two different failure modes and
    leaks lock state to clients sending garbage.
    """
    if not is_pin_format_valid(pin):
        raise HTTPException(400, "PIN должен состоять из 4 цифр")


def _ensure_strong(pin: str) -> None:
    """Reject 4-digit PINs from the leaked-PIN blacklist.

    only invoked on the *new* PIN being committed
    (``/setup``, ``/change`` after old-PIN verification, and
    ``/reset/confirm`` after reset-code verification). On
    ``/check`` we deliberately do NOT block weak PINs — a
    long-time user who picked ``1234`` years ago must still be
    able to log in, otherwise rolling out the blacklist would
    instantly lock thousands of users out.
    """
    if is_pin_too_common(pin):
        raise HTTPException(
            400,
            "Этот PIN слишком простой. Выберите другой, не входящий в список распространённых.",
        )


def _status(user) -> PinStatusOut:
    return PinStatusOut(
        has_pin=bool(user.pin_hash),
        attempts_left=_attempts_left(user),
        locked_until=user.pin_locked_until if _is_locked(user) else None,
        max_attempts=settings.pin_max_attempts,
        session_ttl_seconds=settings.pin_session_ttl_seconds,
    )


def _token_response(user) -> PinTokenOut:
    """Issue a fresh PIN session JWT bound to the user's current epoch.

    The caller is expected to have committed any change to
    ``pin_session_epoch`` before calling this so the issued token's
    claim matches the persisted value, and to have already stamped
    ``pin_last_activity_at`` so the very first protected request
    after unlock isn't immediately rejected as idle-expired by
    ``require_pin_session``.
    """
    token, expires = issue_session_token(user.id, int(user.pin_session_epoch or 0))
    return PinTokenOut(token=token, expires_at=expires)


# ── Endpoints ──────────────────────────────────────────


@router.get("/status", response_model=PinStatusOut)
async def pin_status(user: CurrentUser) -> PinStatusOut:
    return _status(user)


@router.post("/setup", response_model=PinTokenOut)
async def pin_setup(
    body: PinSetupIn, user: CurrentUser, session: SessionDep, _rl: RLPin
) -> PinTokenOut:
    if user.pin_hash:
        raise HTTPException(409, "PIN уже установлен")
    _ensure_format(body.pin)
    _ensure_strong(body.pin)
    user.pin_hash = hash_pin(body.pin)
    user.pin_attempts = 0
    user.pin_locked_until = None
    user.pin_reset_code_hash = None
    user.pin_reset_expires = None
    user.pin_last_activity_at = _now()
    await session.commit()
    return _token_response(user)


@router.post("/check", response_model=PinTokenOut)
async def pin_check(
    body: PinCheckIn, user: CurrentUser, session: SessionDep, _rl: RLPin
) -> PinTokenOut:
    if not user.pin_hash:
        raise HTTPException(409, {"code": "pin_not_set", "detail": "PIN не установлен"})
    _ensure_format(body.pin)
    # Row-lock the user before the RMW on ``pin_attempts`` so two
    # parallel wrong-PIN attempts cannot both read the same value
    # and last-writer-wins the increment (would let an attacker
    # exceed ``pin_max_attempts`` before lockout fires).
    user = await _lock_user_for_pin(session, user)
    if _is_locked(user):
        raise HTTPException(423, "Слишком много попыток. Попробуйте позже.")

    if not verify_pin(body.pin, user.pin_hash):
        user.pin_attempts = (user.pin_attempts or 0) + 1
        if user.pin_attempts >= settings.pin_max_attempts:
            user.pin_locked_until = _now() + timedelta(minutes=settings.pin_lock_minutes)
            user.pin_attempts = 0
            await session.commit()
            raise HTTPException(
                423,
                f"Слишком много попыток. Блокировка на {settings.pin_lock_minutes} мин.",
            )
        await session.commit()
        attempts_left = _attempts_left(user)
        raise HTTPException(
            401,
            f"Неверный PIN. Осталось попыток: {attempts_left}",
        )

    user.pin_attempts = 0
    user.pin_locked_until = None
    user.pin_last_activity_at = _now()
    await session.commit()
    return _token_response(user)


@router.post("/change", response_model=PinTokenOut)
async def pin_change(
    body: PinChangeIn, user: CurrentUser, session: SessionDep, _rl: RLPin
) -> PinTokenOut:
    if not user.pin_hash:
        raise HTTPException(409, "PIN ещё не установлен")
    _ensure_format(body.old_pin)
    _ensure_format(body.new_pin)
    # Row-lock — see ``pin_check`` for the lost-update rationale.
    # Same race applies to the wrong-old-PIN branch below.
    user = await _lock_user_for_pin(session, user)
    if _is_locked(user):
        raise HTTPException(423, "Слишком много попыток. Попробуйте позже.")
    # V5-A-6 (M) / M-10 — wrap the whole sequence in try/except so an
    # unexpected exception (DB connectivity blip, asyncpg protocol
    # error, ORM constraint violation) doesn't leave a partial state
    # behind. Why is this needed on ``/change`` specifically?
    #
    # The wrong-old-PIN branch INCREMENTS ``pin_attempts`` and may
    # WRITE ``pin_locked_until`` before raising HTTPException. Those
    # writes are intentional and have their OWN ``session.commit()``
    # already (see the inner branches): we want lockout-escalation
    # to persist even when the response is an error. So we cannot
    # rely on "raise the exception, let FastAPI's session dep do the
    # rollback at request end" — that would also discard the
    # intentional attempts++ commit.
    #
    # What we DO want to roll back is the happy path's WIP changes
    # if hashing throws (e.g. bcrypt errors out) or the final commit
    # fails (network hiccup): in that case ``user.pin_hash`` was
    # reassigned on the ORM object but the DB never saw it. The
    # surrounding ``except Exception: rollback`` discards that
    # in-memory mutation along with anything autoflushed before the
    # exception. ``HTTPException`` is re-raised untouched so the
    # already-committed attempts++ write stays persisted.
    try:
        if not verify_pin(body.old_pin, user.pin_hash):
            user.pin_attempts = (user.pin_attempts or 0) + 1
            if user.pin_attempts >= settings.pin_max_attempts:
                user.pin_locked_until = _now() + timedelta(minutes=settings.pin_lock_minutes)
                user.pin_attempts = 0
                await session.commit()
                raise HTTPException(
                    423,
                    f"Слишком много попыток. Блокировка на {settings.pin_lock_minutes} мин.",
                )
            await session.commit()
            attempts_left = _attempts_left(user)
            raise HTTPException(
                401,
                f"Старый PIN неверен. Осталось попыток: {attempts_left}",
            )
        # blacklist check happens AFTER verify_pin succeeds
        # so a wrong old-PIN still returns 401 (with the attempts
        # counter bump) and never leaks whether the *new* PIN is
        # acceptable to an attacker who doesn't know the old one.
        _ensure_strong(body.new_pin)
        user.pin_hash = hash_pin(body.new_pin)
        user.pin_attempts = 0
        user.pin_locked_until = None
        # Bump the session epoch so other devices that hold a token
        # for the *old* PIN cannot keep operating after the change.
        # The new token issued below embeds the bumped epoch.
        user.pin_session_epoch = (user.pin_session_epoch or 0) + 1
        user.pin_last_activity_at = _now()
        await session.commit()
        return _token_response(user)
    except HTTPException:
        # Already-handled flow control (wrong PIN, lockout). Commits
        # above are intentional and must persist.
        raise
    except Exception:
        await session.rollback()
        raise


# Per-user PIN-reset throttle. Without this the endpoint could be used
# to either spam DMs at a user or amplify a brute-force against the
# 6-digit code (each new request mints a fresh code, so calling it
# repeatedly multiplies the keyspace explored before lockout).
PIN_RESET_WINDOW_SECONDS = 24 * 60 * 60
PIN_RESET_MAX_PER_WINDOW = 3


async def _mint_and_send_reset_code(user) -> tuple[bool, datetime]:
    """Mint a fresh 6-digit PIN-reset code, stash its hash on ``user``,
    and DM the plaintext code to the user's Telegram. Returns
    ``(delivered, expires_at)``.

    Caller is responsible for ``session.commit()`` so the code-hash
    write is part of the same transaction as any prior balance debit
    (paid path) or counter bump (free path).
    """
    now = _now()
    code = generate_reset_code()
    user.pin_reset_code_hash = hash_reset_code(code)
    user.pin_reset_expires = now + timedelta(seconds=settings.pin_reset_code_ttl_seconds)
    # ``code`` is the plaintext PIN-reset secret — never log it, never
    # put it in ``extra=`` payloads, never echo it back to anyone other
    # than the Telegram recipient. ``send_dm`` ships HTML; we escape
    # the interpolated value as defence-in-depth even though
    # ``generate_reset_code`` returns digits only.
    text = (
        "🔐 Сброс PIN в Garant\n\n"
        f"Ваш код: <b>{html.escape(code)}</b>\n\n"
        "Код действителен 10 минут. Если вы не запрашивали сброс, "
        "просто игнорируйте это сообщение."
    )
    delivered = await send_dm(user.tg_user_id, text)
    if not delivered:
        logger.warning(
            "PIN reset code delivery failed for user %s",
            user.id,
            extra={
                "event": "pin.reset.delivery_failed",
                "user_id": user.id,
            },
        )
    return delivered, user.pin_reset_expires


@router.post("/reset/request", response_model=PinResetRequestOut)
async def pin_reset_request(
    user: CurrentUser, session: SessionDep, _rl: RLPin
) -> PinResetRequestOut:
    # Row-lock so two parallel reset-request calls cannot both pass
    # the ``pin_reset_attempts < PIN_RESET_MAX_PER_WINDOW`` gate,
    # both rewrite ``pin_reset_code_hash``, and both DM the user.
    # The lock also bounds the 6-digit reset-code keyspace an
    # attacker can probe before the ``/reset/confirm`` lockout
    # — exactly the bypass the throttle was added to prevent.
    user = await _lock_user_for_pin(session, user)
    now = _now()
    window_start = user.pin_reset_window_started_at
    elapsed = (now - window_start).total_seconds() if window_start else None
    if window_start is None or (elapsed is not None and elapsed >= PIN_RESET_WINDOW_SECONDS):
        user.pin_reset_window_started_at = now
        user.pin_reset_attempts = 0
    if (user.pin_reset_attempts or 0) >= PIN_RESET_MAX_PER_WINDOW:
        # Compute retry-after so the client can render a friendly message.
        wait_for = int(PIN_RESET_WINDOW_SECONDS - (elapsed or 0))
        raise HTTPException(
            429,
            "Достигнут лимит сбросов PIN. Повторите позже.",
            headers={"Retry-After": str(max(wait_for, 60))},
        )
    user.pin_reset_attempts = (user.pin_reset_attempts or 0) + 1
    delivered, expires_at = await _mint_and_send_reset_code(user)
    await session.commit()
    return PinResetRequestOut(delivered=delivered, expires_at=expires_at)


@router.post("/reset/confirm", response_model=PinTokenOut)
async def pin_reset_confirm(
    body: PinResetConfirmIn,
    user: CurrentUser,
    session: SessionDep,
    _rl: RLPin,
) -> PinTokenOut:
    _ensure_format(body.new_pin)
    # Row-lock — see ``pin_check`` for the RMW-race rationale; this
    # endpoint increments ``pin_attempts`` on wrong reset codes.
    user = await _lock_user_for_pin(session, user)
    if _is_locked(user):
        raise HTTPException(423, "Слишком много попыток. Попробуйте позже.")
    if not user.pin_reset_code_hash or not user.pin_reset_expires:
        raise HTTPException(400, "Сначала запросите код сброса")
    if user.pin_reset_expires < _now():
        user.pin_reset_code_hash = None
        user.pin_reset_expires = None
        await session.commit()
        raise HTTPException(400, "Срок действия кода истёк")
    if not verify_reset_code(body.code, user.pin_reset_code_hash):
        # M-7 — brute-force protection: every wrong code counts the
        # same as a wrong PIN on /check, otherwise an attacker can
        # enumerate the 10⁶-keyspace by spamming /reset/confirm.
        user.pin_attempts = (user.pin_attempts or 0) + 1
        if user.pin_attempts >= settings.pin_max_attempts:
            user.pin_locked_until = _now() + timedelta(minutes=settings.pin_lock_minutes)
            user.pin_attempts = 0
            await session.commit()
            raise HTTPException(
                423,
                f"Слишком много попыток. Блокировка на {settings.pin_lock_minutes} мин.",
            )
        await session.commit()
        attempts_left = _attempts_left(user)
        raise HTTPException(
            401,
            f"Неверный код. Осталось попыток: {attempts_left}",
        )

    # blacklist check happens AFTER verify_reset_code
    # succeeds so attackers who don't know the reset code can't probe
    # which PINs are acceptable (and so a user who got the right
    # reset code never sees their attempts-left counter bump just
    # because they typed a weak new PIN — the brute-force window
    # only protects the code, not the new-PIN field).
    _ensure_strong(body.new_pin)

    user.pin_hash = hash_pin(body.new_pin)
    user.pin_attempts = 0
    user.pin_locked_until = None
    user.pin_reset_code_hash = None
    user.pin_reset_expires = None
    # Bump session epoch so previously-issued tokens stop working
    # the moment a reset lands.
    user.pin_session_epoch = (user.pin_session_epoch or 0) + 1
    user.pin_last_activity_at = _now()
    await session.commit()
    return _token_response(user)


# ── Paid PIN-reset (V14) ───────────────────────────────


async def _usd_currency_or_404(session: AsyncSession) -> Currency:
    """Look up the USD currency row used by the paid PIN-reset flow."""
    row = (
        await session.execute(select(Currency).where(Currency.code == "USD"))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            503,
            "USD валюта не настроена на платформе — обратитесь к администрации",
        )
    return row


async def _pin_reset_price(session: AsyncSession) -> Decimal:
    """Return the admin-configured PIN-reset price (USD)."""
    row = (
        await session.execute(select(AppSettings).order_by(AppSettings.id).limit(1))
    ).scalar_one_or_none()
    if row is None or row.pin_reset_price_usd is None:
        return Decimal("3")
    return Decimal(str(row.pin_reset_price_usd))


@router.get("/reset/price", response_model=PinResetPriceOut)
async def pin_reset_price(user: CurrentUser, session: SessionDep) -> PinResetPriceOut:
    """Return the PIN-reset price + user's USD balance for the paywall modal."""
    price = await _pin_reset_price(session)
    usd = await _usd_currency_or_404(session)
    bal_row = (
        await session.execute(
            select(UserBalance).where(
                UserBalance.user_id == user.id,
                UserBalance.currency_id == usd.id,
            )
        )
    ).scalar_one_or_none()
    balance = Decimal(str(bal_row.amount)) if bal_row is not None else Decimal(0)
    return PinResetPriceOut(
        price=price,
        currency_code=usd.code,
        user_balance=balance,
        can_afford=balance >= price,
    )


@router.post("/reset/paid", response_model=PinResetPaidOut)
async def pin_reset_paid(
    user: CurrentUser, session: SessionDep, _rl: RLPin
) -> PinResetPaidOut:
    """Charge the configured price from the user's USD balance and send
    a fresh 6-digit reset code in Telegram.

    Single transaction: row-lock the user (PIN-counter race), row-lock
    the USD balance, check it covers the price, debit, mint code,
    DM the user, commit. The 24h ``PIN_RESET_MAX_PER_WINDOW`` throttle
    is intentionally skipped because the user paid for this call; the
    per-IP ``RLPin`` limit still applies.
    """
    user = await _lock_user_for_pin(session, user)
    price = await _pin_reset_price(session)
    usd = await _usd_currency_or_404(session)

    if price <= 0:
        # Admin set the price to 0 — mint the code for free so the
        # paywall modal still works.
        delivered, expires_at = await _mint_and_send_reset_code(user)
        await session.commit()
        return PinResetPaidOut(
            delivered=delivered,
            expires_at=expires_at,
            charged=Decimal(0),
            currency_code=usd.code,
        )

    bal = await lock_user_balance(session, user.id, usd.id)
    current = Decimal(str(bal.amount or 0))
    if current < price:
        raise HTTPException(
            402,
            {
                "code": "pin_reset_insufficient",
                "detail": (
                    f"Недостаточно средств на USD-балансе. "
                    f"Нужно {price} USD, доступно {current} USD."
                ),
            },
        )
    bal.amount = current - price
    delivered, expires_at = await _mint_and_send_reset_code(user)
    await session.commit()
    logger.info(
        "PIN reset paid for user %s: charged %s USD",
        user.id,
        price,
        extra={
            "event": "pin.reset.paid",
            "user_id": user.id,
            "charged": str(price),
            "currency": usd.code,
        },
    )
    return PinResetPaidOut(
        delivered=delivered,
        expires_at=expires_at,
        charged=price,
        currency_code=usd.code,
    )
