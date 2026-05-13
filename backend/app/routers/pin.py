"""HTTP endpoints for PIN-code authentication."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

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
    return datetime.now(timezone.utc)


def _is_locked(user) -> bool:
    if user.pin_locked_until is None:
        return False
    locked_until = user.pin_locked_until
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    return locked_until > _now()


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


def _token_response(user_id: int) -> PinTokenOut:
    token, expires = issue_session_token(user_id)
    return PinTokenOut(token=token, expires_at=expires)


# ── Endpoints ──────────────────────────────────────────


@router.get("/status", response_model=PinStatusOut)
async def pin_status(user: CurrentUser) -> PinStatusOut:
    return _status(user)


@router.post("/setup", response_model=PinTokenOut)
async def pin_setup(body: PinSetupIn, user: CurrentUser, session: SessionDep) -> PinTokenOut:
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
    return _token_response(user.id)


@router.post("/check", response_model=PinTokenOut)
async def pin_check(body: PinCheckIn, user: CurrentUser, session: SessionDep) -> PinTokenOut:
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
    return _token_response(user.id)


@router.post("/change", response_model=PinTokenOut)
async def pin_change(body: PinChangeIn, user: CurrentUser, session: SessionDep) -> PinTokenOut:
    if not user.pin_hash:
        raise HTTPException(409, "PIN ещё не установлен")
    _ensure_format(body.old_pin)
    _ensure_format(body.new_pin)
    if _is_locked(user):
        raise HTTPException(423, "Слишком много попыток. Попробуйте позже.")
    if not verify_pin(body.old_pin, user.pin_hash):
        user.pin_attempts = (user.pin_attempts or 0) + 1
        await session.commit()
        raise HTTPException(401, "Старый PIN неверен")
    user.pin_hash = hash_pin(body.new_pin)
    user.pin_attempts = 0
    user.pin_locked_until = None
    await session.commit()
    await session.refresh(user)
    return _token_response(user.id)


@router.post("/reset/request", response_model=PinResetRequestOut)
async def pin_reset_request(user: CurrentUser, session: SessionDep) -> PinResetRequestOut:
    code = generate_reset_code()
    user.pin_reset_code_hash = hash_reset_code(code)
    user.pin_reset_expires = _now() + timedelta(seconds=settings.pin_reset_code_ttl_seconds)
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
        logger.info("PIN reset code for user %s (delivery failed): %s", user.id, code)
    return PinResetRequestOut(delivered=delivered, expires_at=user.pin_reset_expires)


@router.post("/reset/confirm", response_model=PinTokenOut)
async def pin_reset_confirm(
    body: PinResetConfirmIn, user: CurrentUser, session: SessionDep
) -> PinTokenOut:
    _ensure_format(body.new_pin)
    if not user.pin_reset_code_hash or not user.pin_reset_expires:
        raise HTTPException(400, "Сначала запросите код сброса")
    expires = user.pin_reset_expires
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < _now():
        user.pin_reset_code_hash = None
        user.pin_reset_expires = None
        await session.commit()
        raise HTTPException(400, "Срок действия кода истёк")
    if not verify_reset_code(body.code, user.pin_reset_code_hash):
        raise HTTPException(401, "Неверный код")

    user.pin_hash = hash_pin(body.new_pin)
    user.pin_attempts = 0
    user.pin_locked_until = None
    user.pin_reset_code_hash = None
    user.pin_reset_expires = None
    await session.commit()
    await session.refresh(user)
    return _token_response(user.id)
