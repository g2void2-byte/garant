"""Audit v3 A-2 — oversize-payload DLQ.

Pre-fix ``notifier._payload_within_cap`` silently dropped payloads
that exceeded ``NOTIFICATION_PAYLOAD_MAX_BYTES`` with a single
``logger.warning`` line, and the parent ``Notification`` row was
inserted without the payload column.  The dropped data was
effectively lost; only the log line carried the keys/byte count and
the SRE could not join it back to the recipient timeline in a
database query.

This PR adds the ``notification_dlq`` table that the notifier fills
whenever it drops a payload at the cap.  These tests cover both
sides of the cap:

* under-cap payloads ride through ``Notification.payload`` and do
  not produce a DLQ row;
* over-cap payloads land the bare ``Notification`` row (no
  ``payload``) plus a matching ``NotificationDLQ`` row with the
  encoded length, top-level keys, and an excerpt of the JSON.
"""

from __future__ import annotations

from sqlalchemy import select

from tests.helpers import get_user_id_by_tg, signed_init_data


async def _ensure_user(client, tg_id: int, username: str) -> int:
    """Trigger user creation via the existing ``/api/me`` boot path."""
    from backend.app.db import async_session
    from tests.helpers import auth_headers

    init_data = signed_init_data(tg_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init_data))
    assert resp.status_code == 200, resp.text
    async with async_session() as session:
        return await get_user_id_by_tg(session, tg_id)


async def test_under_cap_payload_skips_dlq(client) -> None:
    """A normal-size payload writes the ``Notification`` row and
    leaves the DLQ untouched."""
    from backend.app.db import async_session
    from backend.app.models import NotificationDLQ, NotificationType
    from backend.app.notifier import insert

    user_id = await _ensure_user(client, 901001, "dlq_under_cap")
    payload = {"deal_id": 1, "status": "completed"}
    async with async_session() as session:
        notif, ws_payload = await insert(
            session,
            user_id,
            NotificationType.deals,
            "title",
            "body",
            payload,
        )
        await session.commit()
        assert notif.payload == payload
        assert ws_payload == payload
        rows = (
            (
                await session.execute(
                    select(NotificationDLQ).where(NotificationDLQ.recipient_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        assert rows == []


async def test_over_cap_payload_writes_dlq_row(client) -> None:
    """An oversize payload drops the ``payload`` and lands a DLQ row.

    The DLQ row carries the encoded byte count, the sorted top-level
    keys, and the JSON excerpt — enough metadata to drive an SRE
    "what did we just lose" investigation without grepping logs.
    """
    from backend.app.db import async_session
    from backend.app.models import Notification, NotificationDLQ, NotificationType
    from backend.app.notifier import NOTIFICATION_PAYLOAD_MAX_BYTES, insert

    user_id = await _ensure_user(client, 901002, "dlq_over_cap")
    # Build a payload whose JSON encoding is guaranteed above the
    # 4 KiB cap (``"x" * 8192`` is ~8 KiB once wrapped in quotes
    # and the surrounding object).
    big_blob = "x" * (NOTIFICATION_PAYLOAD_MAX_BYTES * 2)
    payload = {"blob": big_blob, "deal_id": 42, "kind": "big"}
    async with async_session() as session:
        notif, ws_payload = await insert(
            session,
            user_id,
            NotificationType.deals,
            "title",
            "body",
            payload,
        )
        await session.commit()
        # Both the on-wire payload and the stored row payload are
        # dropped to None — the drop is the whole point of the cap.
        assert notif.payload is None
        assert ws_payload is None

        # DLQ row exists and points back to the notification.
        dlq = (
            (
                await session.execute(
                    select(NotificationDLQ).where(NotificationDLQ.recipient_id == user_id)
                )
            )
            .scalars()
            .one()
        )
        assert dlq.notification_id == notif.id
        assert dlq.reason == "payload_over_cap"
        assert dlq.encoded_bytes > NOTIFICATION_PAYLOAD_MAX_BYTES
        # Keys recorded in sorted order for indexable "which producer
        # overshot the cap" queries.
        assert dlq.payload_keys == {"keys": ["blob", "deal_id", "kind"]}
        # Excerpt is the first N bytes of the encoded JSON; bounded
        # so a hostile producer cannot multiply storage by an
        # unbounded factor.
        assert dlq.payload_excerpt is not None
        assert dlq.payload_excerpt.startswith("{")

        # The parent Notification row still exists — the row is
        # never dropped, only its payload is.
        parent = (
            await session.execute(select(Notification).where(Notification.id == notif.id))
        ).scalar_one()
        assert parent.title == "title"
        assert parent.payload is None
