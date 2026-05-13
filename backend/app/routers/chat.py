"""In-deal chat HTTP endpoints (PR-4)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..deps import CurrentUser, PinUser, SessionDep
from ..models import Deal
from ..services_chat import (
    BODY_MAX,
    can_access,
    list_messages,
    mark_read,
    post_user_message,
    total_unread,
    unread_count,
)
from ..services_chat import _serialize as serialize_message

router = APIRouter(prefix="/api/deals", tags=["deal-chat"])


# ── Schemas ────────────────────────────────────────────


class MessageOut(BaseModel):
    id: int
    deal_id: int
    kind: str
    body: str
    attachments: list[dict] = Field(default_factory=list)
    created_at: datetime | None = None
    author: dict | None = None


class MessageList(BaseModel):
    items: list[MessageOut]
    unread: int


class MessageCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=BODY_MAX)


class UnreadOut(BaseModel):
    deal_id: int
    unread: int


class UnreadTotalOut(BaseModel):
    unread: int


# ── Helpers ────────────────────────────────────────────


async def _get(session, deal_id: int) -> Deal:
    deal = await session.get(Deal, deal_id)
    if not deal:
        raise HTTPException(404, "Сделка не найдена")
    return deal


# ── Endpoints ──────────────────────────────────────────


@router.get("/{deal_id}/messages", response_model=MessageList)
async def list_deal_messages(
    deal_id: int,
    user: CurrentUser,
    session: SessionDep,
    after_id: int | None = Query(None, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    deal = await _get(session, deal_id)
    if not await can_access(session, deal, user):
        raise HTTPException(403, "Доступ запрещён")
    msgs = await list_messages(session, deal, after_id=after_id, limit=limit)
    return MessageList(
        items=[MessageOut(**serialize_message(m)) for m in msgs],
        unread=await unread_count(session, deal, user),
    )


@router.post(
    "/{deal_id}/messages", response_model=MessageOut, status_code=201
)
async def send_deal_message(
    deal_id: int,
    body: MessageCreate,
    user: PinUser,
    session: SessionDep,
):
    deal = await _get(session, deal_id)
    try:
        msg = await post_user_message(session, deal, user, body.body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return MessageOut(**serialize_message(msg))


@router.post("/{deal_id}/messages/read", response_model=UnreadOut)
async def mark_deal_messages_read(
    deal_id: int, user: CurrentUser, session: SessionDep
):
    deal = await _get(session, deal_id)
    if not await can_access(session, deal, user):
        raise HTTPException(403, "Доступ запрещён")
    await mark_read(session, deal, user)
    return UnreadOut(deal_id=deal_id, unread=0)


@router.get("/{deal_id}/messages/unread", response_model=UnreadOut)
async def get_deal_unread(
    deal_id: int, user: CurrentUser, session: SessionDep
):
    deal = await _get(session, deal_id)
    if not await can_access(session, deal, user):
        raise HTTPException(403, "Доступ запрещён")
    return UnreadOut(deal_id=deal_id, unread=await unread_count(session, deal, user))


# Mounted on a different prefix so the path stays sane:
#   GET /api/chat/unread-total
unread_router = APIRouter(prefix="/api/chat", tags=["deal-chat"])


@unread_router.get("/unread-total", response_model=UnreadTotalOut)
async def get_total_unread(user: CurrentUser, session: SessionDep):
    return UnreadTotalOut(unread=await total_unread(session, user))
