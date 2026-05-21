"""Audit H2 regression — ``GET /api/deals/{id}/messages`` pages by
``(limit, before_id)`` and batches attachment ``Media`` loading.

Pre-fix the endpoint returned every row in the deal's chat history
unconditionally (no ``LIMIT``) and called the per-message media
resolver in a Python loop, issuing one ``SELECT Media WHERE id IN
(...)`` per message.  For an arbitration that ran for weeks with a
few thousand messages and attachments per message this turned a
single ``GET`` into multi-MB JSON over thousands of subqueries.

The fix:

* New ``limit`` (default 50, max 200) and ``before_id`` cursor query
  params.
* Page ordering: ``ORDER BY id DESC LIMIT N``, returned ascending so
  the chat panel still renders oldest→newest within the slice.
* One ``SELECT Media WHERE id IN (...)`` for the entire page,
  replacing the O(messages) loop of per-message queries.

This file is the regression for those guarantees.  Messages are
seeded directly via ``async_session`` rather than through ``POST
/api/deals/{id}/messages`` because the latter is rate-limited to
30/min and the largest page test posts 60+ rows.
"""

from __future__ import annotations

import json

import pytest

from tests.helpers import (
    auth_headers,
    credit_balance,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)


async def _bootstrap_deal_with_pair(client, *, suffix: str) -> tuple[int, str, int]:
    """Bootstrap buyer+seller, return ``(deal_id, buyer_init, buyer_user_id)``.

    The deal is left in ``pending_confirmation`` (not accepted) — the
    chat endpoint is open to participants regardless of deal status,
    so accepting is unnecessary for the pagination tests.
    """
    from backend.app.db import async_session

    # Pick unique TG ids per parametrize run to keep the seeded
    # principals distinct (``signed_init_data`` keys the rate-limit
    # bucket by user, so a fresh user means a fresh bucket).
    base = abs(hash(suffix)) % 10_000
    buyer_tg = 30_000 + base
    seller_tg = 40_000 + base

    buyer_init = signed_init_data(buyer_tg, f"h2_buyer_{suffix}")
    seller_init = signed_init_data(seller_tg, f"h2_seller_{suffix}")
    buyer_pin = await setup_pin(client, buyer_init)
    await setup_pin(client, seller_init)

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, buyer_tg)
        await credit_balance(session, buyer_id, "USDT", 50)

    create_resp = await client.post(
        "/api/deals",
        json={
            "counterparty": f"h2_seller_{suffix}",
            "role": "buyer",
            "amount": 10,
            "description": f"H2 chat {suffix}",
            "pay_comission": "buyer",
            "currency_code": "USDT",
        },
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    assert create_resp.status_code == 201, create_resp.text
    deal_id = create_resp.json()["id"]

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, buyer_tg)

    return deal_id, buyer_init, buyer_id


async def _seed_messages(
    deal_id: int, sender_id: int, *, count: int, attachment_ids_per: list[int] | None = None
) -> list[int]:
    """Insert ``count`` ``DealMessage`` rows in bulk; return their ids.

    Bypassing the HTTP endpoint avoids the 30/min ``RLDealMessage``
    rate-limit and keeps the test under one second even for the
    "post 60+ messages" case the pre-fix endpoint had to handle.
    """
    from backend.app.db import async_session
    from backend.app.models import DealMessage

    async with async_session() as session:
        rows = []
        for i in range(count):
            attachments_json: str | None = None
            if attachment_ids_per:
                attachments_json = json.dumps(attachment_ids_per)
            rows.append(
                DealMessage(
                    deal_id=deal_id,
                    sender_id=sender_id,
                    text=f"seed {i}",
                    attachments_json=attachments_json,
                )
            )
        session.add_all(rows)
        await session.commit()
        return [r.id for r in rows]


async def _seed_media(owner_id: int, *, count: int) -> list[int]:
    """Create ``count`` ``Media`` rows directly so the attachment
    batching test doesn't have to round-trip ``/api/media/upload``
    (which is also rate-limited).
    """
    from backend.app.db import async_session
    from backend.app.models import Media

    async with async_session() as session:
        rows = [
            Media(
                owner_id=owner_id,
                kind="deal",
                url=f"/media/h2_seed_{i}.png",
                name=f"h2_seed_{i}.png",
                content_type="image/png",
                size=4,
            )
            for i in range(count)
        ]
        session.add_all(rows)
        await session.commit()
        return [r.id for r in rows]


async def test_default_limit_caps_response(client):
    """Audit H2 — without explicit ``limit``, the response is capped
    at the default page size (50). Pre-fix the same request would
    return every single message in the deal.
    """
    deal_id, buyer_init, buyer_id = await _bootstrap_deal_with_pair(client, suffix="default")
    ids = await _seed_messages(deal_id, buyer_id, count=60)
    assert len(ids) == 60

    resp = await client.get(
        f"/api/deals/{deal_id}/messages",
        headers=auth_headers(buyer_init),
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    # Default page caps at 50, and returns the newest 50 in
    # ascending order (oldest of the slice first).
    assert len(items) == 50
    returned_ids = [m["id"] for m in items]
    assert returned_ids == sorted(returned_ids), "page must be ascending"
    assert returned_ids == ids[-50:]


async def test_before_id_cursor_pages_older_history(client):
    """Audit H2 — passing ``before_id`` returns the page strictly
    older than the cursor, so the frontend can prepend the next slice.
    """
    deal_id, buyer_init, buyer_id = await _bootstrap_deal_with_pair(client, suffix="cursor")
    ids = await _seed_messages(deal_id, buyer_id, count=30)

    # Fetch the first (latest) page of 10.
    resp = await client.get(
        f"/api/deals/{deal_id}/messages?limit=10",
        headers=auth_headers(buyer_init),
    )
    page1 = resp.json()
    assert [m["id"] for m in page1] == ids[-10:]

    # Cursor on the oldest of page 1 → next older slice.
    oldest_in_page1 = page1[0]["id"]
    resp2 = await client.get(
        f"/api/deals/{deal_id}/messages?limit=10&before_id={oldest_in_page1}",
        headers=auth_headers(buyer_init),
    )
    page2 = resp2.json()
    assert [m["id"] for m in page2] == ids[-20:-10]
    # No overlap.
    assert page2[-1]["id"] < oldest_in_page1

    # Cursor past the start returns an empty page.
    resp3 = await client.get(
        f"/api/deals/{deal_id}/messages?limit=10&before_id={ids[0]}",
        headers=auth_headers(buyer_init),
    )
    assert resp3.json() == []


@pytest.mark.parametrize(
    "bad_value",
    ["0", "-1", "201", "9999"],
)
async def test_limit_out_of_range_rejected(client, bad_value):
    """Audit H2 — ``limit`` is gated to ``[1, 200]``."""
    deal_id, buyer_init, _ = await _bootstrap_deal_with_pair(client, suffix=f"limit_{bad_value}")
    resp = await client.get(
        f"/api/deals/{deal_id}/messages?limit={bad_value}",
        headers=auth_headers(buyer_init),
    )
    assert resp.status_code == 422, resp.text


async def test_attachments_resolve_across_page(client):
    """Audit H2 — attachments resolve correctly for every message in
    a page.

    The fix changed the per-message media SELECT loop into a single
    ``WHERE id IN (...)``; this test confirms the new code returns
    the same shape (each message keeps its ``attachments`` list,
    correctly hydrated) so the batching does not regress the
    contract.  We don't assert exact query counts here because the
    SQLAlchemy event hooks on the asyncpg engine are unreliable
    across drivers; the behavioural shape is what the frontend
    consumes.
    """
    deal_id, buyer_init, buyer_id = await _bootstrap_deal_with_pair(client, suffix="batch")

    # Seed three media rows and three messages, each attached to one
    # of the media rows in order.
    media_ids = await _seed_media(buyer_id, count=3)

    from backend.app.db import async_session
    from backend.app.models import DealMessage

    msg_ids: list[int] = []
    async with async_session() as session:
        for mid in media_ids:
            row = DealMessage(
                deal_id=deal_id,
                sender_id=buyer_id,
                text=f"with media {mid}",
                attachments_json=json.dumps([mid]),
            )
            session.add(row)
            await session.flush()
            msg_ids.append(row.id)
        await session.commit()

    resp = await client.get(
        f"/api/deals/{deal_id}/messages",
        headers=auth_headers(buyer_init),
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 3

    # Each message has exactly its own seeded media attached — order
    # mirrors message creation order because the page is returned
    # ascending by id.
    for msg, expected_media_id in zip(items, media_ids, strict=True):
        assert len(msg["attachments"]) == 1
        assert msg["attachments"][0]["id"] == expected_media_id


async def test_large_page_size_explicitly_allowed(client):
    """Audit H2 — the hard ceiling is 200; values within range are
    honoured even when the deal has more than the default 50.

    Pre-fix this was a no-op (the endpoint had no ``limit`` at all);
    post-fix the param is parsed and applied.
    """
    deal_id, buyer_init, buyer_id = await _bootstrap_deal_with_pair(client, suffix="large_page")
    await _seed_messages(deal_id, buyer_id, count=120)

    resp = await client.get(
        f"/api/deals/{deal_id}/messages?limit=100",
        headers=auth_headers(buyer_init),
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 100
