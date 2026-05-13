"""Deal chat tests: GET, POST, participant gating, attachments."""

from __future__ import annotations

import io
import json

from sqlalchemy import select

from tests.helpers import (
    auth_headers,
    credit_balance,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)


async def _create_deal(client) -> tuple[int, str, str, str, str]:
    """Spin up a fresh buyer+seller pair and an in_progress deal.

    Returns (deal_id, buyer_init, seller_init, buyer_pin, seller_pin).
    """
    from backend.app.db import async_session

    buyer_init = signed_init_data(2001, "chat_buyer")
    seller_init = signed_init_data(2002, "chat_seller")
    buyer_pin = await setup_pin(client, buyer_init)
    seller_pin = await setup_pin(client, seller_init)

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 2001)
        await credit_balance(session, buyer_id, "USDT", 50)

    create_resp = await client.post(
        "/api/deals",
        json={
            "counterparty": "chat_seller",
            "role": "buyer",
            "sum": 10,
            "currency_code": "USDT",
            "pay_comission": "buyer",
            "description": "chat e2e",
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

    return deal_id, buyer_init, seller_init, buyer_pin, seller_pin


async def test_send_and_list_text_message(client):
    deal_id, buyer_init, seller_init, _, _ = await _create_deal(client)

    # Buyer posts.
    resp = await client.post(
        f"/api/deals/{deal_id}/messages",
        json={"text": "Hello seller", "attachments": []},
        headers=auth_headers(buyer_init),
    )
    assert resp.status_code == 201, resp.text
    msg = resp.json()
    assert msg["text"] == "Hello seller"
    assert msg["attachments"] == []
    assert msg["deal_id"] == deal_id
    assert msg["sender_username"] == "chat_buyer"

    # Seller GETs and sees it.
    list_resp = await client.get(
        f"/api/deals/{deal_id}/messages",
        headers=auth_headers(seller_init),
    )
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    assert items[0]["text"] == "Hello seller"


async def test_non_participant_forbidden(client):
    deal_id, buyer_init, _, _, _ = await _create_deal(client)

    outsider = signed_init_data(2999, "outsider")
    await setup_pin(client, outsider)  # creates the User row

    # GET forbidden.
    resp = await client.get(
        f"/api/deals/{deal_id}/messages",
        headers=auth_headers(outsider),
    )
    assert resp.status_code == 403

    # POST forbidden.
    post = await client.post(
        f"/api/deals/{deal_id}/messages",
        json={"text": "Hi", "attachments": []},
        headers=auth_headers(outsider),
    )
    assert post.status_code == 403

    # Buyer still works.
    own = await client.get(
        f"/api/deals/{deal_id}/messages",
        headers=auth_headers(buyer_init),
    )
    assert own.status_code == 200


async def test_empty_message_rejected(client):
    deal_id, buyer_init, _, _, _ = await _create_deal(client)
    resp = await client.post(
        f"/api/deals/{deal_id}/messages",
        json={"text": "  ", "attachments": []},
        headers=auth_headers(buyer_init),
    )
    assert resp.status_code == 400


async def test_message_with_attachment(client):
    from backend.app.db import async_session
    from backend.app.models import DealMessage

    deal_id, buyer_init, seller_init, _, _ = await _create_deal(client)

    # Upload a 1×1 PNG as a deal attachment.
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc\xfc\xff\xff?\x03\x00\x05\xfe\x02\xfe"
        b"\xa3\x95\xed\x97\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    files = {"file": ("a.png", io.BytesIO(png_bytes), "image/png")}
    up = await client.post(
        "/api/media/upload",
        data={"kind": "deal"},
        files=files,
        headers=auth_headers(buyer_init),
    )
    assert up.status_code == 201, up.text
    media_id = up.json()["id"]

    # Buyer sends a message referencing the upload.
    resp = await client.post(
        f"/api/deals/{deal_id}/messages",
        json={"text": "see attached", "attachments": [media_id]},
        headers=auth_headers(buyer_init),
    )
    assert resp.status_code == 201, resp.text
    msg = resp.json()
    assert len(msg["attachments"]) == 1
    assert msg["attachments"][0]["id"] == media_id
    assert msg["attachments"][0]["kind"] == "deal"

    # Confirm the DB row stored the ids exactly.
    async with async_session() as session:
        row = (
            await session.execute(select(DealMessage).where(DealMessage.id == msg["id"]))
        ).scalar_one()
        assert json.loads(row.attachments_json) == [media_id]

    # Seller can see the attachment too.
    listed = await client.get(
        f"/api/deals/{deal_id}/messages",
        headers=auth_headers(seller_init),
    )
    assert listed.status_code == 200
    seller_view = listed.json()
    assert len(seller_view) == 1
    assert seller_view[0]["attachments"][0]["id"] == media_id


async def test_attachment_must_belong_to_sender(client):
    deal_id, buyer_init, seller_init, _, _ = await _create_deal(client)

    # Seller uploads an attachment of kind="deal".
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    files = {"file": ("x.png", io.BytesIO(png), "image/png")}
    up = await client.post(
        "/api/media/upload",
        data={"kind": "deal"},
        files=files,
        headers=auth_headers(seller_init),
    )
    seller_media_id = up.json()["id"]

    # Buyer tries to reference seller's media — must be rejected.
    resp = await client.post(
        f"/api/deals/{deal_id}/messages",
        json={"text": "borrowed", "attachments": [seller_media_id]},
        headers=auth_headers(buyer_init),
    )
    assert resp.status_code == 400


async def test_unknown_attachment_rejected(client):
    deal_id, buyer_init, _, _, _ = await _create_deal(client)
    resp = await client.post(
        f"/api/deals/{deal_id}/messages",
        json={"text": "ghost", "attachments": [99999]},
        headers=auth_headers(buyer_init),
    )
    assert resp.status_code == 400


async def test_ordering_oldest_first(client):
    deal_id, buyer_init, seller_init, _, _ = await _create_deal(client)

    for text in ("first", "second", "third"):
        sender = buyer_init if text != "second" else seller_init
        resp = await client.post(
            f"/api/deals/{deal_id}/messages",
            json={"text": text, "attachments": []},
            headers=auth_headers(sender),
        )
        assert resp.status_code == 201

    listed = await client.get(
        f"/api/deals/{deal_id}/messages",
        headers=auth_headers(buyer_init),
    )
    assert listed.status_code == 200
    items = listed.json()
    assert [m["text"] for m in items] == ["first", "second", "third"]
