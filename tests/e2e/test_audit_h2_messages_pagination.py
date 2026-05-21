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

This file is the regression for those guarantees.
"""

from __future__ import annotations

import io

import pytest

from tests.helpers import (
    auth_headers,
    credit_balance,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
    tiny_image_bytes,
)


async def _create_deal_and_pair(client, *, suffix: str) -> tuple[int, str, str]:
    """Bootstrap a buyer+seller pair plus an in_progress deal.

    Returns ``(deal_id, buyer_init, seller_init)`` — PIN tokens are
    not threaded back because the chat endpoint is not PIN-gated.
    """
    from backend.app.db import async_session

    buyer_tg = 30_000 + (hash(suffix) % 1000)
    seller_tg = 31_000 + (hash(suffix) % 1000)

    buyer_init = signed_init_data(buyer_tg, f"h2_buyer_{suffix}")
    seller_init = signed_init_data(seller_tg, f"h2_seller_{suffix}")
    buyer_pin = await setup_pin(client, buyer_init)
    seller_pin = await setup_pin(client, seller_init)

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

    accept_resp = await client.post(
        f"/api/deals/{deal_id}/accept",
        headers={**auth_headers(seller_init), "X-Pin-Token": seller_pin},
    )
    assert accept_resp.status_code == 200, accept_resp.text

    return deal_id, buyer_init, seller_init


async def _post_messages(client, deal_id: int, init: str, *, count: int) -> list[int]:
    """Post ``count`` plain-text messages, return the ids in order."""
    ids: list[int] = []
    for i in range(count):
        resp = await client.post(
            f"/api/deals/{deal_id}/messages",
            json={"text": f"msg {i}", "attachments": []},
            headers=auth_headers(init),
        )
        assert resp.status_code == 201, resp.text
        ids.append(resp.json()["id"])
    return ids


async def test_default_limit_caps_response(client):
    """Audit H2 — without explicit ``limit``, the response is capped
    at the default page size (50). Pre-fix the same request would
    return every single message in the deal.
    """
    deal_id, buyer_init, _ = await _create_deal_and_pair(client, suffix="default")
    # Post 60 messages, more than the default page size.
    ids = await _post_messages(client, deal_id, buyer_init, count=60)
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
    deal_id, buyer_init, _ = await _create_deal_and_pair(client, suffix="cursor")
    ids = await _post_messages(client, deal_id, buyer_init, count=30)

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
    "bad_value,expected",
    [
        ("0", 422),
        ("-1", 422),
        ("201", 422),
        ("9999", 422),
    ],
)
async def test_limit_out_of_range_rejected(client, bad_value, expected):
    """Audit H2 — ``limit`` is gated to ``[1, 200]``."""
    deal_id, buyer_init, _ = await _create_deal_and_pair(client, suffix=f"limit_{bad_value}")
    resp = await client.get(
        f"/api/deals/{deal_id}/messages?limit={bad_value}",
        headers=auth_headers(buyer_init),
    )
    assert resp.status_code == expected, resp.text


async def test_attachments_batched_one_select(client):
    """Audit H2 — attachments for every message in the page are
    loaded in a single ``SELECT Media WHERE id IN (...)``, not one
    query per message.

    We assert behaviour (attachments resolve correctly across the
    whole page) and query count (one ``SELECT FROM media`` for the
    list endpoint).
    """
    from sqlalchemy import event

    from backend.app.db import get_engine

    deal_id, buyer_init, _ = await _create_deal_and_pair(client, suffix="batch")

    # Upload three media rows and attach one to each of three messages.
    media_ids: list[int] = []
    for i in range(3):
        up = await client.post(
            "/api/media/upload",
            data={"kind": "deal"},
            files={"file": (f"a{i}.png", io.BytesIO(tiny_image_bytes("PNG")), "image/png")},
            headers=auth_headers(buyer_init),
        )
        assert up.status_code == 201, up.text
        media_ids.append(up.json()["id"])

    for mid in media_ids:
        resp = await client.post(
            f"/api/deals/{deal_id}/messages",
            json={"text": "with attachment", "attachments": [mid]},
            headers=auth_headers(buyer_init),
        )
        assert resp.status_code == 201, resp.text

    # Count the number of ``FROM media`` SELECTs issued during the
    # list call.  ``before_cursor_execute`` fires once per actual SQL
    # statement so multi-statement abuse would show up here.
    media_selects: list[str] = []

    engine = get_engine()
    sync_engine = engine.sync_engine

    def _watch(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        lowered = statement.lower()
        if " from media" in lowered and lowered.lstrip().startswith("select"):
            media_selects.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _watch)
    try:
        resp = await client.get(
            f"/api/deals/{deal_id}/messages",
            headers=auth_headers(buyer_init),
        )
    finally:
        event.remove(sync_engine, "before_cursor_execute", _watch)

    assert resp.status_code == 200, resp.text
    items = resp.json()
    # Three messages with one attachment each.
    assert len(items) == 3
    for msg, expected_media_id in zip(items, media_ids, strict=True):
        assert len(msg["attachments"]) == 1
        assert msg["attachments"][0]["id"] == expected_media_id

    # Exactly one ``SELECT ... FROM media`` for the whole page —
    # pre-fix this list would have len == 3 (one per message).
    assert len(media_selects) == 1, media_selects
