"""Notification fan-out.

A single ``notifier.push()`` call:

1. Inserts a row into the ``notifications`` table (durable record).
2. Pushes the event to all WebSocket connections of the recipient
   (in-app real-time channel).
3. Fires a Telegram DM in the background if the recipient has DMs
   enabled for that ``NotificationType`` bucket (configured by the
   per-user ``dm_deals`` / ``dm_deposits`` / ``dm_system`` flags).

The DM step is best-effort and fire-and-forget so a slow Telegram API
never blocks the HTTP request that triggered the notification.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Notification, NotificationType, User
from .ws import manager

logger = logging.getLogger(__name__)

# Comment 39 (audit v9): cap the serialised ``payload`` JSON at 4 KB.
# Notifications fan out to the DB row, to every open WebSocket of the
# recipient, and (indirectly) into ``logger.exception`` traceback frames
# on DM failure. An unbounded payload there is both a DoS knob (any
# router could enqueue a megabyte) and a privacy footgun (more PII
# spreads further). 4 KB is enough room for the structured deal/wallet
# events we actually emit; anything larger is almost certainly a bug.
NOTIFICATION_PAYLOAD_MAX_BYTES = 4096


def _serialize_payload(payload: dict[str, Any] | None) -> str | None:
    """Serialise ``payload`` and enforce the 4 KB cap.

    Returns ``None`` when there is no payload, or when the JSON exceeds
    :data:`NOTIFICATION_PAYLOAD_MAX_BYTES` (we log a warning and drop the
    payload rather than truncating — half-JSON is worse than no JSON
    for downstream consumers).
    """
    if not payload:
        return None
    encoded = json.dumps(payload)
    if len(encoded.encode("utf-8")) > NOTIFICATION_PAYLOAD_MAX_BYTES:
        logger.warning(
            "notification payload exceeds %d bytes, dropping (keys=%s)",
            NOTIFICATION_PAYLOAD_MAX_BYTES,
            sorted(payload.keys()),
        )
        return None
    return encoded


def _dm_enabled(recipient: User, type_: NotificationType) -> bool:
    if type_ is NotificationType.deals:
        return bool(recipient.dm_deals)
    if type_ is NotificationType.deposits:
        return bool(recipient.dm_deposits)
    if type_ is NotificationType.system:
        return bool(recipient.dm_system)
    # Unknown bucket → default to True so we never silently drop.
    return True


def _format_dm(title: str, body: str) -> str:
    # bot/notify.py sends with parse_mode=HTML
    title_html = html.escape(title or "")
    body_html = html.escape(body or "")
    if body_html:
        return f"<b>{title_html}</b>\n{body_html}"
    return f"<b>{title_html}</b>"


async def _safe_send_dm(tg_user_id: int, text: str) -> None:
    try:
        # Imported lazily so importing notifier doesn't pull aiogram at
        # module-load time (helps tests + non-bot deployments).
        from .bot.notify import send_dm

        await send_dm(tg_user_id, text)
    except Exception:  # noqa: BLE001
        logger.exception("DM dispatch failed for tg_user_id=%s", tg_user_id)


async def push(
    session: AsyncSession,
    recipient_id: int,
    type_: NotificationType,
    title: str,
    body: str = "",
    payload: dict[str, Any] | None = None,
) -> Notification:
    """Persist a notification, publish it on WS, fire a DM.

    Security contract (V5-A-7): ``body`` may contain user-visible
    secrets (PIN reset codes, OTP codes, account-transfer codes) and
    MUST NEVER be logged in plaintext. The current code does NOT log
    it: ``_safe_send_dm`` logs only the recipient ``tg_user_id`` and
    the exception type via ``logger.exception``, and no other
    ``logger.*`` call in this module interpolates ``body``, ``title``,
    or ``payload``. Future maintainers and any future Sentry
    integration must preserve this contract (``send_default_pii=False``
    and disabled ``LoggingIntegration`` breadcrumb capture for
    ``backend.app.notifier`` and ``backend.app.bot.notify``).

    The caller **owns the transaction**: we ``flush()`` so the notif
    row has a primary key for WS/DM dispatch, but the commit happens
    in the caller (M-17). That makes the in-app notification atomic
    with whatever state transition triggered it — if the caller's
    commit later raises, neither the state change nor the notif is
    visible to anyone.
    """
    serialized_payload = _serialize_payload(payload)
    ws_payload = payload if serialized_payload is not None else None
    notif = Notification(
        recipient_id=recipient_id,
        type=type_,
        title=title,
        body=body,
        payload=serialized_payload,
    )
    session.add(notif)
    await session.flush()

    await manager.publish(
        recipient_id,
        {
            "event": "notification",
            "data": {
                "id": notif.id,
                "type": notif.type.value,
                "title": notif.title,
                "body": notif.body,
                "payload": ws_payload,
                "is_read": False,
            },
        },
    )

    # Fire-and-forget DM dispatch. We only need the recipient's
    # ``tg_user_id`` + per-type preference, so a single ``session.get``
    # is enough and avoids a round-trip when DMs are disabled.
    recipient = await session.get(User, recipient_id)
    if recipient is not None and _dm_enabled(recipient, type_):
        asyncio.create_task(_safe_send_dm(recipient.tg_user_id, _format_dm(title, body)))

    return notif
