"""Deal chat endpoints.

In-app chat for the two parties of a deal (and admins/arbiters during
arbitration). Messages may carry up to 10 attachments — references to
``Media`` rows uploaded separately through ``POST /api/media/upload``
with ``kind="deal"``.

Real-time delivery uses the existing notifier WebSocket channel by
pushing a ``deal_message`` event directly. We *don't* go through
``notifier.push`` because storing every chat line in the ``notifications``
table — and sending a Telegram DM for each — would be too noisy.
Notification rows only get created for events that warrant a badge
(state transitions, arbitration, payments, etc.).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..deps import CurrentUser, SessionDep
from ..models import Deal, DealMessage, Media
from ..rate_limit import RLDealMessage
from ..schemas import DealMessageCreate, DealMessageOut, MediaOut
from ..ws import manager

router = APIRouter(prefix="/api/deals", tags=["deal-messages"])


async def _load_deal_or_403(session, deal_id: int, user) -> Deal:
    deal = await session.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "Сделка не найдена")
    is_participant = user.id in (deal.buyer_id, deal.seller_id)
    is_staff = bool(user.is_admin or user.is_arbiter)
    if not (is_participant or is_staff):
        raise HTTPException(403, "Нет доступа к чату этой сделки")
    return deal


def _media_out(m: Media) -> MediaOut:
    return MediaOut(
        id=m.id,
        kind=m.kind,
        url=m.url,
        name=m.name,
        size=m.size,
        content_type=m.content_type,
        created_at=m.created_at,
    )


async def _serialize(session, msg: DealMessage) -> DealMessageOut:
    attachments: list[MediaOut] = []
    if msg.attachments_json:
        try:
            ids = json.loads(msg.attachments_json)
        except ValueError:
            ids = []
        if isinstance(ids, list) and ids:
            rows = (
                (
                    await session.execute(
                        select(Media).where(
                            Media.id.in_(
                                [int(i) for i in ids if isinstance(i, int) or str(i).isdigit()]
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
            by_id = {m.id: m for m in rows}
            for raw in ids:
                try:
                    mid = int(raw)
                except (TypeError, ValueError):
                    continue
                if mid in by_id:
                    attachments.append(_media_out(by_id[mid]))

    return DealMessageOut(
        id=msg.id,
        deal_id=msg.deal_id,
        sender_id=msg.sender_id,
        sender_username=msg.sender.username if msg.sender else None,
        text=msg.text,
        attachments=attachments,
        created_at=msg.created_at,
    )


@router.get("/{deal_id}/messages", response_model=list[DealMessageOut])
async def list_messages(
    deal_id: int,
    user: CurrentUser,
    session: SessionDep,
) -> list[DealMessageOut]:
    await _load_deal_or_403(session, deal_id, user)
    rows = (
        (
            await session.execute(
                select(DealMessage)
                .where(DealMessage.deal_id == deal_id)
                .order_by(DealMessage.created_at.asc(), DealMessage.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return [await _serialize(session, m) for m in rows]


@router.post(
    "/{deal_id}/messages",
    response_model=DealMessageOut,
    status_code=201,
)
async def create_message(
    deal_id: int,
    body: DealMessageCreate,
    user: CurrentUser,
    session: SessionDep,
    _rl: RLDealMessage,
) -> DealMessageOut:
    deal = await _load_deal_or_403(session, deal_id, user)

    text = (body.text or "").strip()
    if not text and not body.attachments:
        raise HTTPException(400, "Сообщение не может быть пустым")

    attachment_ids: list[int] = []
    if body.attachments:
        rows = (
            (await session.execute(select(Media).where(Media.id.in_(body.attachments))))
            .scalars()
            .all()
        )
        by_id = {m.id: m for m in rows}
        for raw in body.attachments:
            media = by_id.get(raw)
            if media is None:
                raise HTTPException(400, f"Вложение {raw} не найдено")
            if media.owner_id != user.id:
                raise HTTPException(400, f"Вложение {raw} принадлежит другому пользователю")
            if media.kind != "deal":
                raise HTTPException(400, f"Вложение {raw} имеет недопустимый kind")
            attachment_ids.append(media.id)

    msg = DealMessage(
        deal_id=deal_id,
        sender_id=user.id,
        text=text,
        attachments_json=json.dumps(attachment_ids) if attachment_ids else None,
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)

    out = await _serialize(session, msg)

    # Fan out to the other participant's WebSocket. We deliberately skip
    # ``notifier.push`` (no notifications row, no DM) to avoid spamming
    # the badge/DM pipeline on every chat line.
    other_id = deal.seller_id if user.id == deal.buyer_id else deal.buyer_id
    event: dict[str, Any] = {
        "event": "deal_message",
        "data": out.model_dump(mode="json"),
    }
    await manager.publish(other_id, event)

    return out
