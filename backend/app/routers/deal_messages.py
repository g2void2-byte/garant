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

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..deps import CurrentUser, SessionDep
from ..media_signing import signed_media_url
from ..models import TERMINAL_DEAL_STATUSES, Deal, DealMessage, DealStatus, Media
from ..rate_limit import RLDealMessage
from ..schemas import DealMessageCreate, DealMessageOut, MediaOut
from ..ws import manager

# Audit H2 — default page size and hard ceiling for the chat list.
# Pre-fix the endpoint returned the entire history (no ``LIMIT``),
# which for an arbitration that ran for months would routinely
# serialise 10k+ messages × up to 10 attachments each. The default is
# tuned for an initial chat-panel render; the frontend pages older
# messages in via the ``before_id`` cursor.
_DEFAULT_MESSAGE_PAGE = 50
_MAX_MESSAGE_PAGE = 200

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
    # Audit v3 L-14 — sign deal-bucket URLs at serialisation time so
    # the link returned to the chat panel goes stale after
    # ``settings.media_signed_url_ttl_seconds``. Pre-fix the link
    # used to live indefinitely on the unsigned ``StaticFiles``
    # mount.
    return MediaOut(
        id=m.id,
        kind=m.kind,
        url=signed_media_url(url=m.url, kind=m.kind),
        name=m.name,
        size=m.size,
        content_type=m.content_type,
        created_at=m.created_at,
    )


def _parse_attachment_ids(attachments_json: str | None) -> list[int]:
    if not attachments_json:
        return []
    try:
        raw = json.loads(attachments_json)
    except ValueError:
        return []
    if not isinstance(raw, list):
        return []
    ids: list[int] = []
    for item in raw:
        if isinstance(item, bool):
            # ``bool`` is a subclass of ``int`` in Python — reject explicitly
            # so a stored ``true`` cannot be reinterpreted as media id ``1``.
            continue
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def _serialize_one(msg: DealMessage, media_by_id: dict[int, Media]) -> DealMessageOut:
    attachments: list[MediaOut] = []
    for mid in _parse_attachment_ids(msg.attachments_json):
        media = media_by_id.get(mid)
        if media is not None:
            attachments.append(_media_out(media))
    return DealMessageOut(
        id=msg.id,
        deal_id=msg.deal_id,
        sender_id=msg.sender_id,
        sender_username=msg.sender.username if msg.sender else None,
        text=msg.text,
        attachments=attachments,
        created_at=msg.created_at,
    )


async def _serialize(session, msg: DealMessage) -> DealMessageOut:
    """Single-message serialiser — used by ``POST`` and WS fan-out.

    The list endpoint uses ``_serialize_one`` directly against a
    pre-fetched ``media_by_id`` map (Audit H2) so it issues exactly
    one ``SELECT Media WHERE id IN (...)`` for the whole page instead
    of one per message.
    """
    ids = _parse_attachment_ids(msg.attachments_json)
    media_by_id: dict[int, Media] = {}
    if ids:
        rows = (await session.execute(select(Media).where(Media.id.in_(ids)))).scalars().all()
        media_by_id = {m.id: m for m in rows}
    return _serialize_one(msg, media_by_id)


@router.get("/{deal_id}/messages", response_model=list[DealMessageOut])
async def list_messages(
    deal_id: int,
    user: CurrentUser,
    session: SessionDep,
    limit: int = Query(
        _DEFAULT_MESSAGE_PAGE,
        ge=1,
        le=_MAX_MESSAGE_PAGE,
        description="Maximum number of messages to return (newest within the window).",
    ),
    before_id: int | None = Query(
        None,
        ge=1,
        description=(
            "Cursor — return only messages with ``id`` strictly less than this. "
            "Use the ``id`` of the oldest already-loaded message to fetch the "
            "next older page."
        ),
    ),
) -> list[DealMessageOut]:
    await _load_deal_or_403(session, deal_id, user)
    # Audit H2 — pre-fix this endpoint returned ``SELECT * FROM
    # deal_messages WHERE deal_id = :id`` without ``LIMIT``. An
    # arbitration that ran for weeks could accumulate 10k+ rows, and a
    # bot polling the endpoint every few seconds (or even just an open
    # browser tab) would hammer the DB and serialise multi-MB JSON
    # responses. We now page by ``(created_at DESC, id DESC)`` with a
    # cursor on ``id``, then re-sort the page ascending so the existing
    # chat panel — which appends new messages at the bottom and pulls
    # older ones at the top — can render the slice without resorting.
    #
    # ``DealMessage.sender`` already declares ``lazy="selectin"`` on the
    # model, so the senders are batched into a single follow-up SELECT;
    # calling ``selectinload`` explicitly here is belt-and-braces.
    stmt = (
        select(DealMessage)
        .where(DealMessage.deal_id == deal_id)
        .options(selectinload(DealMessage.sender))
        .order_by(DealMessage.id.desc())
        .limit(limit)
    )
    if before_id is not None:
        stmt = stmt.where(DealMessage.id < before_id)
    page = (await session.execute(stmt)).scalars().all()
    rows = list(reversed(page))
    # Audit H2 — batch the attachment ``Media`` rows for the whole page
    # into a single ``SELECT ... WHERE id IN (...)`` instead of the
    # previous O(messages) per-message subquery.
    all_media_ids: set[int] = set()
    for msg in rows:
        all_media_ids.update(_parse_attachment_ids(msg.attachments_json))
    media_by_id: dict[int, Media] = {}
    if all_media_ids:
        media_rows = (
            (await session.execute(select(Media).where(Media.id.in_(all_media_ids))))
            .scalars()
            .all()
        )
        media_by_id = {m.id: m for m in media_rows}
    return [_serialize_one(m, media_by_id) for m in rows]


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
    # specific deal id. Participants can chat in every non-terminal
    # state (``pending_confirmation``, ``in_progress``,
    # ``pending_cancellation``, ``arbitration`` — see
    # ``tests/e2e/test_deal_messages.py::test_messages_still_allowed_in_active_statuses``).
    # Staff (admins / arbiters) may also post into ``resolved_*`` so
    # they can record a verdict / explanation.
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
