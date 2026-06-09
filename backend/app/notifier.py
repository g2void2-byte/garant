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
from collections.abc import Coroutine
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Notification, NotificationDLQ, NotificationType, User
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

# Audit v3 A-2 — when a payload is dropped at the cap the encoded JSON
# is excerpted to the DLQ table (``notification_dlq``) for forensic
# recovery. Keep the excerpt small enough that a hostile producer
# flooding oversize payloads can't multiply the storage cost by more
# than ~2× the parent cap. 8 KiB lets the SRE eyeball a reasonable
# chunk of the dropped JSON while still bounding the worst case.
NOTIFICATION_PAYLOAD_DLQ_EXCERPT_BYTES = 8192


# Audit M-3 — strong references for fire-and-forget DM tasks.
# ``asyncio.create_task`` only holds a weak reference to the wrapped
# coroutine; if no caller keeps the returned ``Task`` alive the GC can
# collect it mid-await and the DM is silently lost (Python emits a
# "Task was destroyed but it is pending!" warning at runtime). The set
# is module-level so every notifier dispatch shares the same anchor,
# and ``Task.add_done_callback(_discard)`` evicts the entry once the
# DM completes so the set doesn't grow unbounded.
_dm_dispatch_tasks: set[asyncio.Task[None]] = set()


def _spawn_dm_task(coro: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(coro)
    _dm_dispatch_tasks.add(task)
    task.add_done_callback(_dm_dispatch_tasks.discard)


class _PayloadCapResult:
    """Result of :func:`_check_payload_cap` — payload + DLQ metadata.

    Pre-fix ``_payload_within_cap`` returned the (possibly-None)
    payload and silently lost the metadata on a drop.  Audit v3 A-2
    needs the drop metadata so ``insert``/``insert_bare`` can
    persist it to ``notification_dlq`` for forensic recovery, but
    keeping the call site shape ``stored, ws_payload = ...`` minimises
    the churn at the existing callers.

    ``stored`` is what goes to ``Notification.payload`` (None on drop
    or empty input).  ``dlq_excerpt`` / ``dlq_encoded_bytes`` /
    ``dlq_keys`` are populated only on the over-cap drop path; all
    three being ``None`` / ``0`` / ``None`` means "fits, nothing to
    DLQ".
    """

    __slots__ = ("stored", "dlq_excerpt", "dlq_encoded_bytes", "dlq_keys")

    def __init__(
        self,
        stored: dict[str, Any] | None,
        dlq_excerpt: str | None = None,
        dlq_encoded_bytes: int = 0,
        dlq_keys: list[str] | None = None,
    ) -> None:
        self.stored = stored
        self.dlq_excerpt = dlq_excerpt
        self.dlq_encoded_bytes = dlq_encoded_bytes
        self.dlq_keys = dlq_keys

    @property
    def was_dropped(self) -> bool:
        return self.dlq_excerpt is not None


def _check_payload_cap(payload: dict[str, Any] | None) -> _PayloadCapResult:
    """Enforce :data:`NOTIFICATION_PAYLOAD_MAX_BYTES` and capture DLQ metadata.

    Returns a :class:`_PayloadCapResult` carrying both the value to
    persist on ``Notification.payload`` and (on the over-cap path) the
    excerpt + keys + byte count for the matching ``NotificationDLQ``
    row.  Pre-fix the metadata only lived in the ``logger.warning``
    line; persisting it lets the SRE join "row N had its payload
    dropped" back to "the dropped JSON started with these keys / was
    this many bytes" without grepping logs.

    V11-M-10 — ``Notification.payload`` is a JSONB column mapped to
    ``dict | None``; the DB layer serialises the dict itself so we no
    longer hand a pre-encoded string to the ORM.  The size check still
    runs through ``json.dumps`` so the cap is enforced against the
    on-the-wire encoding rather than Python object size.
    """
    if not payload:
        return _PayloadCapResult(stored=None)
    encoded = json.dumps(payload)
    encoded_bytes = len(encoded.encode("utf-8"))
    if encoded_bytes > NOTIFICATION_PAYLOAD_MAX_BYTES:
        keys = sorted(payload.keys())
        # V11-L-15 — structured-logging fields so the JSON-logger
        # downstream (Loki/Sentry) can pivot on event/size without
        # regexing the message body. Drop the payload (do NOT
        # truncate) — half-JSON would be worse than no JSON for
        # downstream consumers.
        logger.warning(
            "notification payload exceeds %d bytes, dropping (keys=%s)",
            NOTIFICATION_PAYLOAD_MAX_BYTES,
            keys,
            extra={
                "event": "notifier.payload.over_cap",
                "encoded_bytes": encoded_bytes,
                "cap_bytes": NOTIFICATION_PAYLOAD_MAX_BYTES,
                "payload_keys": keys,
            },
        )
        return _PayloadCapResult(
            stored=None,
            dlq_excerpt=encoded[:NOTIFICATION_PAYLOAD_DLQ_EXCERPT_BYTES],
            dlq_encoded_bytes=encoded_bytes,
            dlq_keys=keys,
        )
    return _PayloadCapResult(stored=payload)


def _payload_within_cap(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Back-compat shim: return the stored payload only.

    Several call sites (e.g. fan-out broadcasts that don't write a
    ``Notification`` row) still call ``_payload_within_cap`` directly;
    they care only about "what goes on the wire" and have no row to
    attach a DLQ entry to.  Keep the historical name pointing at the
    drop-only path so those callers stay untouched.
    """
    return _check_payload_cap(payload).stored


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
    cap = _check_payload_cap(payload)
    stored_payload = cap.stored
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
    # Audit v3 A-2 — on an over-cap drop persist the metadata + a
    # bounded excerpt to ``notification_dlq`` so the SRE can join
    # back to ``notifications.id`` and inspect what was lost.  The
    # excerpt itself is JSON-text (UTF-8) capped at
    # ``NOTIFICATION_PAYLOAD_DLQ_EXCERPT_BYTES`` — the encoded length
    # is stored separately for the (rare) case where the dropped
    # JSON exceeds the excerpt cap.  The DLQ row stays in the same
    # transaction as the parent notification so a rollback elsewhere
    # in the caller doesn't leave a half-recorded drop.
    if cap.was_dropped:
        session.add(
            NotificationDLQ(
                notification_id=notif.id,
                recipient_id=recipient_id,
                reason="payload_over_cap",
                encoded_bytes=cap.dlq_encoded_bytes,
                payload_keys={"keys": cap.dlq_keys or []},
                payload_excerpt=cap.dlq_excerpt,
            )
        )
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
                "created_at": notif.created_at.isoformat(),
            },
        },
    )
    recipient = await session.get(User, notif.recipient_id)
    if recipient is not None and _dm_enabled(recipient, notif.type):
        # Audit M-3 — route through ``_spawn_dm_task`` so the returned
        # task is anchored in a module-level set until it finishes.
        # Bare ``asyncio.create_task(...)`` drops the only strong
        # reference at the end of the expression, letting the GC reap
        # the task mid-await and silently lose the DM.
        _spawn_dm_task(
            _safe_send_dm(
                recipient.tg_user_id,
                _format_dm(notif.title, notif.body),
                notif_type=notif.type.value,
                payload=ws_payload,
            )
        )


async def publish_deal_update(
    deal_id: int,
    recipient_ids: list[int] | tuple[int, ...],
    *,
    status: str | None = None,
) -> None:
    """Broadcast a transient ``deal.updated`` cache-invalidation signal.

    Item 22 — the existing ``notification`` event only reaches the
    *recipient* of a stored ``Notification`` row, so the initiator of
    a state-changing op (and any other participant we never wrote a
    notification for) keeps a stale React Query cache until the next
    poll / focus refetch. ``deal.updated`` fans out to every party
    that should re-pull the deal (typically buyer + seller, plus the
    arbiter on arbitration ops) without inserting a DB row — it's a
    pure WS-level cache-bust.

    Failures are swallowed and logged: a missing socket or a Redis
    publish error must never bubble up and surface a 500 on an
    otherwise successful deal op.
    """
    seen: set[int] = set()
    payload: dict[str, Any] = {"deal_id": deal_id}
    if status is not None:
        payload["status"] = status
    for recipient_id in recipient_ids:
        if recipient_id in seen:
            continue
        seen.add(recipient_id)
        try:
            await manager.publish(
                recipient_id,
                {"event": "deal.updated", "data": payload},
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "deal.updated publish failed for recipient_id=%s deal_id=%s",
                recipient_id,
                deal_id,
                extra={
                    "event": "notifier.deal_updated.publish.failed",
                    "recipient_id": recipient_id,
                    "deal_id": deal_id,
                },
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
