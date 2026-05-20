"""HTTP endpoints for the PR-CA account-transfer flow."""

from __future__ import annotations

import html
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..bot.notify import send_dm
from ..deps import CurrentUser, PinUser, SessionDep
from ..rate_limit import RLPin
from ..services_account import (
    cancel_active,
    confirm_transfer,
    get_active_code,
    issue_code,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/account/transfer", tags=["account"])


# ── DTO ────────────────────────────────────────────────


class TransferStatusOut(BaseModel):
    has_active: bool
    expires_at: datetime | None = None


class TransferStartOut(BaseModel):
    delivered: bool
    expires_at: datetime


class TransferConfirmIn(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class TransferConfirmOut(BaseModel):
    ok: bool
    tg_user_id: int


# ── Endpoints ──────────────────────────────────────────


@router.get("/status", response_model=TransferStatusOut)
async def transfer_status(user: CurrentUser, session: SessionDep) -> TransferStatusOut:
    row = await get_active_code(session, user.id)
    if row is None:
        return TransferStatusOut(has_active=False)
    return TransferStatusOut(has_active=True, expires_at=row.expires_at)


@router.post("/start", response_model=TransferStartOut)
async def transfer_start(user: PinUser, session: SessionDep) -> TransferStartOut:
    code, expires = await issue_code(session, user)
    # 5.4 (MED) — ``send_dm`` ships ``text`` with ``parse_mode=HTML``
    # (see ``bot/notify.py::get_bot``). Every interpolated value
    # below MUST pass through ``html.escape`` even when the source is
    # server-controlled (``issue_code`` returns digits only), so a
    # future change that adds user-supplied input (e.g. a display
    # name, deeplink) cannot accidentally inject HTML / Telegram
    # entities and impersonate the admin. The static ``<b>...</b>``
    # wrappers stay un-escaped because they are the only markup we
    # *want* the Telegram client to render.
    # *** DO NOT INTERPOLATE UNESCAPED USER INPUT BELOW. ***
    text = (
        "🔁 Перенос аккаунта в Garant\n\n"
        f"Ваш код: <b>{html.escape(code)}</b>\n\n"
        "Введите его в приложении на новом Telegram-аккаунте, чтобы "
        "перенести профиль. Код действителен 15 минут.\n\n"
        "Если вы не запрашивали перенос — игнорируйте это сообщение."
    )
    delivered = await send_dm(user.tg_user_id, text)
    if not delivered:
        # V11-L-15 — structured-logging fields so the JSON-logger
        # downstream (Loki/Sentry) can pivot on event/user_id without
        # regexing the message body. ``code`` / ``text`` are NOT in
        # ``extra`` — the plaintext transfer code is a one-shot
        # secret and must never appear in logs.
        logger.warning(
            "account transfer code delivery failed for user %s",
            user.id,
            extra={
                "event": "account_transfer.delivery_failed",
                "user_id": user.id,
            },
        )
    return TransferStartOut(delivered=delivered, expires_at=expires)


@router.post("/cancel", response_model=TransferStatusOut)
async def transfer_cancel(user: PinUser, session: SessionDep) -> TransferStatusOut:
    await cancel_active(session, user)
    return TransferStatusOut(has_active=False)


@router.post("/confirm", response_model=TransferConfirmOut)
async def transfer_confirm(
    body: TransferConfirmIn,
    user: CurrentUser,
    session: SessionDep,
    _rl: RLPin,
) -> TransferConfirmOut:
    # Brute-force protection for the 6-digit code: ``RLPin`` caps each
    # caller at 5 req/min, codes live for 15 min, and the keyspace is
    # 10⁶ — combined per-attempt success probability ≤0.005 %. There is
    # no per-code attempt counter; see ``services_account`` for the
    # security argument.
    try:
        source = await confirm_transfer(session, user, body.code)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    # The source user keeps its PIN; the frontend drops its local PIN
    # token after a successful response and PinGate re-prompts.
    return TransferConfirmOut(ok=True, tg_user_id=source.tg_user_id)
