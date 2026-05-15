"""V5-D-1 (M) — ``GET /api/notifications`` cursor pagination.

The legacy endpoint returned the latest 200 rows unconditionally. A
client with > 200 unread notifications could never reach the older
entries, and removing the cap would let one user with thousands of
notifications generate a single oversized SELECT on each refresh.

Fix: cap the page size at 200 and add a keyset cursor on
``(created_at, id)`` so clients can page deeper. The tuple is
required because two notifications inserted in the same bulk fanout
can share a ``created_at`` value — paging by ``created_at`` alone
would silently skip or duplicate rows at the boundary.

Test plan:

1. Seed 250 notifications for one user.
2. First page (no cursor) returns 200 rows.
3. Pass ``before_created_at`` + ``before_id`` from the last row of
   page 1 → page 2 returns the remaining 50 rows.
4. The union of both pages must equal the full set with NO
   duplicates and NO missing rows.
5. Two notifications sharing a ``created_at`` (the multi-recipient
   fanout shape) must page deterministically too.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import Notification, NotificationType
from tests.helpers import auth_headers, signed_init_data


async def _bootstrap(client, *, tg_user_id: int, username: str) -> int:
    """Walk the /api/me bootstrap and return the resulting user id."""
    init = signed_init_data(tg_user_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _seed_n_notifications(recipient_id: int, n: int) -> list[int]:
    """Bulk-insert ``n`` notifications spread one second apart so the
    keyset cursor sees a strictly decreasing ``created_at`` sequence.

    Returns the ids in insertion order (oldest first). The endpoint
    returns DESC, so paging will see them reversed.
    """
    # Notification.created_at is TIMESTAMP WITHOUT TIME ZONE — keep
    # the datetimes naive so asyncpg doesn't reject them at the wire.
    base = datetime(2024, 1, 1)
    rows: list[Notification] = []
    async with async_session() as session:
        for i in range(n):
            rows.append(
                Notification(
                    recipient_id=recipient_id,
                    type=NotificationType.deals,
                    title=f"notif #{i}",
                    body=f"body for notif {i}",
                    created_at=base + timedelta(seconds=i),
                )
            )
        session.add_all(rows)
        await session.commit()
        for r in rows:
            await session.refresh(r)
        return [r.id for r in rows]


async def test_250_notifications_paginate_without_duplicates_or_gaps(client):
    """V5-D-1 — 250 rows → first page 200, second page 50, union ≡ all 250."""
    init = signed_init_data(8501, "notif_pager")
    user_id = await _bootstrap(client, tg_user_id=8501, username="notif_pager")

    all_ids = await _seed_n_notifications(user_id, 250)
    expected_ids = set(all_ids)
    assert len(expected_ids) == 250

    # Page 1 — no cursor, must return 200 rows in DESC(created_at, id) order.
    page1 = await client.get("/api/notifications", headers=auth_headers(init))
    assert page1.status_code == 200, page1.text
    page1_rows = page1.json()
    assert len(page1_rows) == 200, len(page1_rows)

    # Page 2 — cursor = (created_at, id) of the last row in page 1.
    cursor_row = page1_rows[-1]
    page2 = await client.get(
        "/api/notifications",
        params={
            "before_created_at": cursor_row["created_at"],
            "before_id": cursor_row["id"],
        },
        headers=auth_headers(init),
    )
    assert page2.status_code == 200, page2.text
    page2_rows = page2.json()
    assert len(page2_rows) == 50, len(page2_rows)

    seen_ids = [r["id"] for r in page1_rows] + [r["id"] for r in page2_rows]
    # No duplicates between pages.
    assert len(seen_ids) == len(set(seen_ids)), "duplicate ids across pages"
    # No missing rows.
    assert set(seen_ids) == expected_ids


async def test_pagination_handles_shared_created_at_tie(client):
    """V5-D-1 — when two rows share a ``created_at`` value (the
    notifier fanout shape), the ``(created_at, id)`` keyset must
    still page through them deterministically — no skips, no
    duplicates.

    A naïve cursor on ``created_at`` alone would either:

    * miss the second row entirely (using ``<`` and skipping ties), or
    * include the first row twice (using ``<=``).

    The router uses ``(created_at < cursor) OR (created_at == cursor
    AND id < cursor_id)`` precisely to handle this.
    """
    init = signed_init_data(8511, "notif_tie")
    user_id = await _bootstrap(client, tg_user_id=8511, username="notif_tie")

    # Five rows all stamped at the same created_at, plus two more
    # at distinct earlier times so the total is 7 (above the page
    # size we'll use).
    shared_ts = datetime(2024, 6, 1, 12, 0, 0)
    earlier_ts = datetime(2024, 6, 1, 11, 0, 0)
    even_earlier_ts = datetime(2024, 6, 1, 10, 0, 0)

    async with async_session() as session:
        rows = []
        for i in range(5):
            rows.append(
                Notification(
                    recipient_id=user_id,
                    type=NotificationType.deals,
                    title=f"tie #{i}",
                    body="",
                    created_at=shared_ts,
                )
            )
        rows.append(
            Notification(
                recipient_id=user_id,
                type=NotificationType.deals,
                title="earlier",
                body="",
                created_at=earlier_ts,
            )
        )
        rows.append(
            Notification(
                recipient_id=user_id,
                type=NotificationType.deals,
                title="even earlier",
                body="",
                created_at=even_earlier_ts,
            )
        )
        session.add_all(rows)
        await session.commit()

    # Walk pages of size 3 across 7 rows.
    seen: list[int] = []
    cursor: dict[str, object] | None = None
    for _ in range(10):  # bounded to avoid an infinite loop on a regression
        params: dict[str, object] = {"limit": 3}
        if cursor is not None:
            params.update(cursor)
        resp = await client.get("/api/notifications", params=params, headers=auth_headers(init))
        assert resp.status_code == 200, resp.text
        page = resp.json()
        if not page:
            break
        for row in page:
            seen.append(row["id"])
        cursor = {
            "before_created_at": page[-1]["created_at"],
            "before_id": page[-1]["id"],
        }

    # Total 7 rows must be visible — no duplicates and no skips.
    assert len(seen) == 7, seen
    assert len(set(seen)) == 7, seen

    # Cross-check against the actual DB content for the same user.
    async with async_session() as session:
        all_ids = {
            row.id
            for row in (
                await session.execute(
                    select(Notification).where(Notification.recipient_id == user_id)
                )
            )
            .scalars()
            .all()
        }
    assert set(seen) == all_ids


async def test_invalid_before_created_at_returns_400(client):
    """Sanity: a malformed cursor 400s rather than silently
    returning the whole list — otherwise a client bug could
    mask a regression in cursor parsing."""
    await _bootstrap(client, tg_user_id=8521, username="notif_bad_cursor")
    init = signed_init_data(8521, "notif_bad_cursor")
    resp = await client.get(
        "/api/notifications",
        params={"before_created_at": "not-an-iso-date", "before_id": 1},
        headers=auth_headers(init),
    )
    assert resp.status_code == 400, resp.text


async def test_first_page_respects_explicit_limit(client):
    """Belt-and-braces: explicit ``limit`` is honoured up to the cap.
    Requested limit=10 → 10 rows. Requested limit=999 → Pydantic
    rejects (422) because the upper bound is 200."""
    user_id = await _bootstrap(client, tg_user_id=8531, username="notif_limit")
    await _seed_n_notifications(user_id, 25)
    init = signed_init_data(8531, "notif_limit")

    resp = await client.get("/api/notifications", params={"limit": 10}, headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 10

    # Above the cap → Pydantic Query validator rejects.
    resp = await client.get("/api/notifications", params={"limit": 999}, headers=auth_headers(init))
    assert resp.status_code == 422, resp.text
