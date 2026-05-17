"""HTTP endpoints for the PR-CA account-transfer flow."""

from __future__ import annotations

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
    text = (
        "🔁 Перенос аккаунта в Garant\n\n"
        f"Ваш код: <b>{code}</b>\n\n"
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
    # ``RLPin`` (5/min per caller) caps the request rate at the network
    # edge; ``confirm_transfer`` enforces an in-DB per-code attempt
    # counter so an attacker can't churn the 10⁶ keyspace from many
    # IPs and hijack any active transfer.
    try:
        source = await confirm_transfer(session, user, body.code)
    except ValueError as e:
        raise HTTPException(400, str(e))
    # The source user keeps its PIN; the frontend drops its local PIN
    # token after a successful response and PinGate re-prompts.
    return TransferConfirmOut(ok=True, tg_user_id=source.tg_user_id)
