"""In-deal chat (PR-4).

Each deal has a single chat with messages written by participants and
system-emitted rows on every state transition. WS pushes are addressed
to the existing per-user channel (``ws.manager.send_to_user``); the
client decides whether the deal is currently open and routes the event
to the chat panel or to the notifications badge.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Deal,
    DealMessage,
    DealMessageKind,
    DealReadMarker,
    DealStatus,
    User,
)
from .ws import manager

logger = logging.getLogger(__name__)

BODY_MAX = 4000


# ── Recipients ─────────────────────────────────────────


async def _arbitration_staff(session: AsyncSession) -> list[User]:
    rows = (
        await session.execute(
            select(User).where(
                (User.is_admin.is_(True)) | (User.is_arbiter.is_(True))
            )
        )
    ).scalars().all()
    return list(rows)


async def chat_audience(session: AsyncSession, deal: Deal) -> list[int]:
    """User ids that can read / be WS-pushed for this deal.

    Always the buyer + seller; once a deal hits arbitration we add every
    admin and arbiter so they can see the dispute context.
    """
    ids: set[int] = {deal.buyer_id, deal.seller_id}
    if deal.status == DealStatus.arbitration:
        for staff in await _arbitration_staff(session):
            ids.add(staff.id)
    ids.discard(None)  # type: ignore[arg-type]
    return [i for i in ids if i is not None]


# ── Serialisation ──────────────────────────────────────


def _serialize(msg: DealMessage) -> dict[str, Any]:
    author = msg.author
    return {
        "id": msg.id,
        "deal_id": msg.deal_id,
        "kind": msg.kind.value,
        "body": msg.body,
        "attachments": json.loads(msg.attachments_json or "[]"),
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
        "author": (
            None
            if author is None
            else {
                "id": author.id,
                "tg_user_id": author.tg_user_id,
                "username": author.username,
                "display_name": author.display_name,
                "photo_url": author.photo_url,
            }
        ),
    }


# ── Reading ────────────────────────────────────────────


async def list_messages(
    session: AsyncSession,
    deal: Deal,
    *,
    after_id: int | None = None,
    limit: int = 100,
) -> list[DealMessage]:
    stmt = (
        select(DealMessage)
        .where(DealMessage.deal_id == deal.id)
        .order_by(DealMessage.id.asc())
        .limit(max(1, min(limit, 500)))
    )
    if after_id is not None:
        stmt = stmt.where(DealMessage.id > after_id)
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def can_access(session: AsyncSession, deal: Deal, user: User) -> bool:
    if user.id in (deal.buyer_id, deal.seller_id):
        return True
    if deal.status == DealStatus.arbitration and (
        user.is_admin or user.is_arbiter
    ):
        return True
    return False


# ── Read markers ───────────────────────────────────────


async def _get_marker(
    session: AsyncSession, deal_id: int, user_id: int
) -> DealReadMarker | None:
    return (
        await session.execute(
            select(DealReadMarker).where(
                and_(
                    DealReadMarker.deal_id == deal_id,
                    DealReadMarker.user_id == user_id,
                )
            )
        )
    ).scalar_one_or_none()


async def mark_read(session: AsyncSession, deal: Deal, user: User) -> datetime:
    """Bump the user's read marker for this deal to ``now``.

    Returns the new ``last_read_at`` timestamp.
    """
    marker = await _get_marker(session, deal.id, user.id)
    now = datetime.utcnow()
    if marker is None:
        marker = DealReadMarker(deal_id=deal.id, user_id=user.id, last_read_at=now)
        session.add(marker)
    else:
        marker.last_read_at = now
    await session.commit()
    await manager.send_to_user(
        user.id,
        {"event": "deal_messages_read", "data": {"deal_id": deal.id}},
    )
    return now


async def unread_count(
    session: AsyncSession, deal: Deal, user: User
) -> int:
    marker = await _get_marker(session, deal.id, user.id)
    stmt = select(func.count(DealMessage.id)).where(
        DealMessage.deal_id == deal.id,
        DealMessage.author_id != user.id,
    )
    if marker is not None:
        stmt = stmt.where(DealMessage.created_at > marker.last_read_at)
    return int((await session.execute(stmt)).scalar_one() or 0)


async def total_unread(session: AsyncSession, user: User) -> int:
    """Sum of unread deal-chat messages across every deal of the user."""
    deals = (
        await session.execute(
            select(Deal).where(
                (Deal.buyer_id == user.id) | (Deal.seller_id == user.id)
            )
        )
    ).scalars().all()
    total = 0
    for deal in deals:
        total += await unread_count(session, deal, user)
    return total


# ── Writing ────────────────────────────────────────────


async def post_user_message(
    session: AsyncSession,
    deal: Deal,
    author: User,
    body: str,
) -> DealMessage:
    body = (body or "").strip()
    if not body:
        raise ValueError("Сообщение не может быть пустым")
    if len(body) > BODY_MAX:
        raise ValueError(f"Сообщение слишком длинное (максимум {BODY_MAX} символов)")
    if not await can_access(session, deal, author):
        raise ValueError("Нет доступа к чату этой сделки")
    if deal.status in {
        DealStatus.cancelled,
        DealStatus.completed,
        DealStatus.resolved_for_buyer,
        DealStatus.resolved_for_seller,
        DealStatus.cancelled_for_inactivity,
    }:
        raise ValueError("Чат сделки закрыт")

    msg = DealMessage(
        deal_id=deal.id,
        author_id=author.id,
        body=body,
        kind=DealMessageKind.user,
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)

    await _broadcast(session, deal, msg, exclude_user_id=author.id)
    return msg


async def post_system_message(
    session: AsyncSession, deal: Deal, body: str
) -> DealMessage:
    """Drop a system-kind row into the deal chat.

    Used by ``services_deals.py`` after every state transition.
    """
    body = (body or "").strip()
    if not body:
        return  # type: ignore[return-value]
    msg = DealMessage(
        deal_id=deal.id,
        author_id=None,
        body=body,
        kind=DealMessageKind.system,
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    await _broadcast(session, deal, msg, exclude_user_id=None)
    return msg


async def _broadcast(
    session: AsyncSession,
    deal: Deal,
    msg: DealMessage,
    *,
    exclude_user_id: int | None,
) -> None:
    payload = {"event": "deal_message", "data": _serialize(msg)}
    for uid in await chat_audience(session, deal):
        if uid == exclude_user_id:
            # author already has the message in their local optimistic
            # state; skip the duplicate ack push.
            continue
        await manager.send_to_user(uid, payload)
