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
from sqlalchemy.orm import selectinload

from ..deps import CurrentUser, SessionDep
from ..models import TERMINAL_DEAL_STATUSES, Deal, DealMessage, DealStatus, Media
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
    # ``DealMessage.sender`` already declares ``lazy="selectin"`` on the
    # model, so the senders are batched into a single follow-up SELECT
    # — calling ``selectinload`` explicitly here is belt-and-braces:
    # if the model's lazy strategy ever changes, the explicit option
    # keeps this hot endpoint O(1) queries instead of O(messages).
    rows = (
        (
            await session.execute(
                select(DealMessage)
                .where(DealMessage.deal_id == deal_id)
                .options(selectinload(DealMessage.sender))
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

    # Comment 37 (H, harassment) — block new chat messages on deals
    # that are already in a terminal state. Pre-fix, the loser of a
    # deal (or any party after completion / cancellation) could keep
    # writing into the chat forever — a harassment vector that the
    # block / mute UI does not cover because the chat is scoped to a
    # specific deal id. Participants can chat only while the deal is
    # actively running (``pending_confirmation``, ``in_progress``,
    # ``pending_cancellation``). Staff (admins / arbiters) may still
    # send messages into ``arbitration`` / ``resolved_*`` rows so
    # they can post a verdict / explanation.
    is_staff = bool(user.is_admin or user.is_arbiter)
    _STAFF_TERMINAL_OK = {
        DealStatus.resolved_for_buyer,
        DealStatus.resolved_for_seller,
    }
    if deal.status in TERMINAL_DEAL_STATUSES:
        if not (is_staff and deal.status in _STAFF_TERMINAL_OK):
            raise HTTPException(409, "Чат сделки закрыт")

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

    # Fan out to the other party's WebSocket. We deliberately skip
    # ``notifier.push`` (no notifications row, no DM) to avoid spamming
    # the badge/DM pipeline on every chat line.
    #
    # When the sender is a participant we only need to broadcast to the
    # opposite party. When the sender is staff (admin / arbiter writing
    # into the deal chat) we broadcast to *both* buyer and seller, so
    # both sides see the staff message in real time.
    event: dict[str, Any] = {
        "event": "deal_message",
        "data": out.model_dump(mode="json"),
    }
    if user.id in (deal.buyer_id, deal.seller_id):
        other_id = deal.seller_id if user.id == deal.buyer_id else deal.buyer_id
        await manager.publish(other_id, event)
    else:
        await manager.publish(deal.buyer_id, event)
        await manager.publish(deal.seller_id, event)

    return out
