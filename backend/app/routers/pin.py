"""HTTP endpoints for PIN-code authentication."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..bot.notify import send_dm
from ..config import settings
from ..deps import CurrentUser, SessionDep
from ..pin import (
    generate_reset_code,
    hash_pin,
    hash_reset_code,
    is_pin_format_valid,
    issue_session_token,
    verify_pin,
    verify_reset_code,
)
from ..rate_limit import RLPin

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


# ── Helpers ────────────────────────────────────────────


def _now() -> datetime:
    # Tz-naive UTC to match ``DateTime`` columns in the DB. Postgres
    # rejects tz-aware values written to ``TIMESTAMP WITHOUT TIME ZONE``.
    return datetime.utcnow()


def _is_locked(user) -> bool:
    if user.pin_locked_until is None:
        return False
    return user.pin_locked_until > _now()


def _attempts_left(user) -> int:
    return max(0, settings.pin_max_attempts - (user.pin_attempts or 0))


def _ensure_format(pin: str) -> None:
    if not is_pin_format_valid(pin):
        raise HTTPException(400, "PIN должен состоять из 4 цифр")


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
    claim matches the persisted value.
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
    user.pin_hash = hash_pin(body.pin)
    user.pin_attempts = 0
    user.pin_locked_until = None
    user.pin_reset_code_hash = None
    user.pin_reset_expires = None
    await session.commit()
    await session.refresh(user)
    return _token_response(user)


@router.post("/check", response_model=PinTokenOut)
async def pin_check(
    body: PinCheckIn, user: CurrentUser, session: SessionDep, _rl: RLPin
) -> PinTokenOut:
    if not user.pin_hash:
        raise HTTPException(409, "PIN не установлен")
    _ensure_format(body.pin)
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
    await session.commit()
    await session.refresh(user)
    return _token_response(user)


@router.post("/change", response_model=PinTokenOut)
async def pin_change(
    body: PinChangeIn, user: CurrentUser, session: SessionDep, _rl: RLPin
) -> PinTokenOut:
    if not user.pin_hash:
        raise HTTPException(409, "PIN ещё не установлен")
    _ensure_format(body.old_pin)
    _ensure_format(body.new_pin)
    if _is_locked(user):
        raise HTTPException(423, "Слишком много попыток. Попробуйте позже.")
    # M-10 — make sure any unexpected DB error rolls the transaction
    # back; without it a half-applied update (e.g. attempts++ but
    # pin_hash unchanged) could leak across the request boundary if a
    # later session.commit() ever succeeds in the same request.
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
        user.pin_hash = hash_pin(body.new_pin)
        user.pin_attempts = 0
        user.pin_locked_until = None
        await session.commit()
        await session.refresh(user)
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


@router.post("/reset/request", response_model=PinResetRequestOut)
async def pin_reset_request(
    user: CurrentUser, session: SessionDep, _rl: RLPin
) -> PinResetRequestOut:
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

    code = generate_reset_code()
    user.pin_reset_code_hash = hash_reset_code(code)
    user.pin_reset_expires = now + timedelta(seconds=settings.pin_reset_code_ttl_seconds)
    await session.commit()
    await session.refresh(user)

    text = (
        "🔐 Сброс PIN в Garant\n\n"
        f"Ваш код: <b>{code}</b>\n\n"
        "Код действителен 10 минут. Если вы не запрашивали сброс, "
        "просто игнорируйте это сообщение."
    )
    delivered = await send_dm(user.tg_user_id, text)
    if not delivered:
        logger.warning("PIN reset code delivery failed for user %s", user.id)
    return PinResetRequestOut(delivered=delivered, expires_at=user.pin_reset_expires)


@router.post("/reset/confirm", response_model=PinTokenOut)
async def pin_reset_confirm(
    body: PinResetConfirmIn,
    user: CurrentUser,
    session: SessionDep,
    _rl: RLPin,
) -> PinTokenOut:
    _ensure_format(body.new_pin)
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

    user.pin_hash = hash_pin(body.new_pin)
    user.pin_attempts = 0
    user.pin_locked_until = None
    user.pin_reset_code_hash = None
    user.pin_reset_expires = None
    await session.commit()
    await session.refresh(user)
    return _token_response(user)
