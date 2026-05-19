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


def _payload_within_cap(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate that ``payload`` serialises under :data:`NOTIFICATION_PAYLOAD_MAX_BYTES`.

    Returns the payload unchanged when it fits, ``None`` when it is
    missing, and ``None`` (with a ``logger.warning`` line) when the
    JSON encoding exceeds the cap. V11-M-10 — ``Notification.payload``
    is now a JSONB column mapped to ``dict | None``; the DB layer
    serialises the dict itself, so we no longer hand a pre-encoded
    string to the ORM (which would double-encode into a JSON-string
    literal). The size check still happens through ``json.dumps`` so
    the cap is enforced against the on-the-wire encoding rather than
    Python object size.
    """
    if not payload:
        return None
    encoded = json.dumps(payload)
    encoded_bytes = len(encoded.encode("utf-8"))
    if encoded_bytes > NOTIFICATION_PAYLOAD_MAX_BYTES:
        # V11-L-15 — structured-logging fields so the JSON-logger
        # downstream (Loki/Sentry) can pivot on event/size without
        # regexing the message body. Drop the payload (do NOT
        # truncate) — half-JSON would be worse than no JSON for
        # downstream consumers.
        logger.warning(
            "notification payload exceeds %d bytes, dropping (keys=%s)",
            NOTIFICATION_PAYLOAD_MAX_BYTES,
            sorted(payload.keys()),
            extra={
                "event": "notifier.payload.over_cap",
                "encoded_bytes": encoded_bytes,
                "cap_bytes": NOTIFICATION_PAYLOAD_MAX_BYTES,
                "payload_keys": sorted(payload.keys()),
            },
        )
        return None
    return payload


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


async def _safe_send_dm(
    tg_user_id: int,
    text: str,
    *,
    notif_type: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    try:
        # Imported lazily so importing notifier doesn't pull aiogram at
        # module-load time (helps tests + non-bot deployments).
        from .bot.keyboards import notification_keyboard
        from .bot.notify import send_dm

        reply_markup = None
        if notif_type is not None:
            try:
                reply_markup = notification_keyboard(notif_type, payload)
            except Exception:
                # A broken keyboard must never block the DM — fall
                # back to a plain text message instead of swallowing
                # the notification entirely.
                logger.exception(
                    "notification_keyboard failed for type=%s",
                    notif_type,
                    extra={
                        "event": "notifier.dm.keyboard.failed",
                        "notif_type": notif_type,
                    },
                )
                reply_markup = None
        await send_dm(tg_user_id, text, reply_markup=reply_markup)
    except Exception as exc:  # noqa: BLE001
        # V11-L-15 — structured-logging fields so the JSON-logger
        # downstream (Loki/Sentry) can pivot on event/recipient
        # without regexing the message body. ``text`` is deliberately
        # NOT in ``extra`` because it can carry user-visible secrets
        # (PIN reset codes, OTP, etc.) — see ``bot.notify.send_dm``.
        logger.exception(
            "DM dispatch failed for tg_user_id=%s",
            tg_user_id,
            extra={
                "event": "notifier.dm.unexpected_exception",
                "tg_user_id": tg_user_id,
                "error_class": type(exc).__name__,
            },
        )


async def insert(
    session: AsyncSession,
    recipient_id: int,
    type_: NotificationType,
    title: str,
    body: str = "",
    payload: dict[str, Any] | None = None,
) -> tuple[Notification, dict[str, Any] | None]:
    """Insert + flush a Notification row WITHOUT WS/DM dispatch."""
    stored_payload = _payload_within_cap(payload)
    ws_payload = stored_payload
    notif = Notification(
        recipient_id=recipient_id,
        type=type_,
        title=title,
        body=body,
        payload=stored_payload,
    )
    session.add(notif)
    await session.flush()
    return notif, ws_payload


async def dispatch_after_commit(
    session: AsyncSession,
    notif: Notification,
    ws_payload: dict[str, Any] | None,
) -> None:
    """WS publish + DM dispatch for a previously-inserted notification."""
    await manager.publish(
        notif.recipient_id,
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
    recipient = await session.get(User, notif.recipient_id)
    if recipient is not None and _dm_enabled(recipient, notif.type):
        asyncio.create_task(
            _safe_send_dm(
                recipient.tg_user_id,
                _format_dm(notif.title, notif.body),
                notif_type=notif.type.value,
                payload=ws_payload,
            )
        )


async def push(
    session: AsyncSession,
    recipient_id: int,
    type_: NotificationType,
    title: str,
    body: str = "",
    payload: dict[str, Any] | None = None,
) -> Notification:
    """Persist a notification, publish it on WS, fire a DM.

    Convenience wrapper: ``insert()`` + ``dispatch_after_commit()``.
    Use the split API when you need to defer WS/DM dispatch until
    after a ``session.commit()`` (e.g. in batch sweeps).
    """
    notif, ws_payload = await insert(
        session,
        recipient_id,
        type_,
        title,
        body,
        payload,
    )
    await dispatch_after_commit(session, notif, ws_payload)
    return notif
