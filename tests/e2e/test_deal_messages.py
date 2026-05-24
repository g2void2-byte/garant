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
    tiny_image_bytes,
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
            "amount": 10,
            "currency_code": "USDT",
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

    # Upload a 1×1 PNG as a deal attachment.  ``tiny_image_bytes``
    # round-trips through Pillow so it survives the L-5 re-encode
    # gate on ``/api/media/upload``.
    png_bytes = tiny_image_bytes("PNG")
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
    png = tiny_image_bytes("PNG")
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


async def test_arbiter_can_write_in_deal_chat(client):
    """PR-B: arbiter (and admin) can write into the deal chat even if
    they aren't buyer/seller. Their message reaches both parties."""
    from backend.app.db import async_session
    from backend.app.models import User

    deal_id, buyer_init, seller_init, _, _ = await _create_deal(client)

    arb_init = signed_init_data(9999, "arb_user")
    me_resp = await client.get("/api/me", headers=auth_headers(arb_init))
    assert me_resp.status_code == 200
    arb_id = me_resp.json()["id"]
    async with async_session() as session:
        u = await session.get(User, arb_id)
        assert u is not None
        u.is_arbiter = True
        await session.commit()

    resp = await client.post(
        f"/api/deals/{deal_id}/messages",
        json={"text": "Arbiter speaking", "attachments": []},
        headers=auth_headers(arb_init),
    )
    assert resp.status_code == 201, resp.text
    msg = resp.json()
    assert msg["text"] == "Arbiter speaking"
    assert msg["sender_username"] == "arb_user"

    # Buyer sees the message
    listed = await client.get(f"/api/deals/{deal_id}/messages", headers=auth_headers(buyer_init))
    assert listed.status_code == 200
    assert any(m["text"] == "Arbiter speaking" for m in listed.json())

    # Seller sees the message
    listed = await client.get(f"/api/deals/{deal_id}/messages", headers=auth_headers(seller_init))
    assert listed.status_code == 200
    assert any(m["text"] == "Arbiter speaking" for m in listed.json())


async def test_random_user_cannot_write_in_deal_chat(client):
    """Non-staff, non-participant users still get 403."""
    deal_id, *_ = await _create_deal(client)
    init = signed_init_data(7777, "stranger")
    await client.get("/api/me", headers=auth_headers(init))
    resp = await client.post(
        f"/api/deals/{deal_id}/messages",
        json={"text": "hi", "attachments": []},
        headers=auth_headers(init),
    )
    assert resp.status_code == 403


# ── Comment 37 (H, harassment) — terminal-status blocking ──────────────


async def _set_status(deal_id: int, status):
    """Force a deal into ``status`` so the test doesn't have to drive
    the state machine each time. The terminal-status blocking lives in
    the chat router, not in the deal transition logic, so the route
    we take to reach the status is irrelevant for this regression."""
    from backend.app.db import async_session
    from backend.app.models import Deal

    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        assert deal is not None
        deal.status = status
        await session.commit()


async def _make_staff(client, *, tg_id: int, username: str, role: str) -> str:
    """Bootstrap a fresh user and grant them ``role`` ("admin" or
    "arbiter"). Returns the signed initData for use in
    ``auth_headers``."""
    from backend.app.db import async_session
    from backend.app.models import User

    init = signed_init_data(tg_id, username)
    me = await client.get("/api/me", headers=auth_headers(init))
    assert me.status_code == 200, me.text
    uid = me.json()["id"]
    async with async_session() as session:
        u = await session.get(User, uid)
        assert u is not None
        if role == "admin":
            u.is_admin = True
        elif role == "arbiter":
            u.is_arbiter = True
        else:
            raise ValueError(f"bad role: {role}")
        await session.commit()
    return init


async def test_participant_cannot_message_in_any_terminal_status(client):
    """Comment 37 — participants (buyer/seller) get 409 in every
    terminal state. We probe each of the five terminal values: closed
    chat means closed chat, regardless of *how* the deal ended.

    Reusing one deal across statuses is safe because the 409 is
    immediate — no DB write side-effects — and we re-stamp the status
    each iteration."""
    from backend.app.models import DealStatus

    deal_id, buyer_init, seller_init, _, _ = await _create_deal(client)

    terminal_states = [
        DealStatus.cancelled,
        DealStatus.completed,
        DealStatus.resolved_for_buyer,
        DealStatus.resolved_for_seller,
        DealStatus.cancelled_for_inactivity,
    ]
    for st in terminal_states:
        await _set_status(deal_id, st)
        for who, init in (("buyer", buyer_init), ("seller", seller_init)):
            resp = await client.post(
                f"/api/deals/{deal_id}/messages",
                json={"text": f"after {st.value}", "attachments": []},
                headers=auth_headers(init),
            )
            assert resp.status_code == 409, f"{who}@{st.value}: {resp.status_code} {resp.text}"


async def test_staff_can_message_only_in_resolved_terminal(client):
    """Comment 37 — staff (admin or arbiter) can post a closing
    explanation only in ``resolved_for_buyer`` / ``resolved_for_seller``.
    Other terminal states (``cancelled``, ``completed``,
    ``cancelled_for_inactivity``) close the chat for everyone.

    Pick one admin and one arbiter so we cover both branches of the
    ``is_admin or is_arbiter`` guard.
    """
    from backend.app.models import DealStatus

    deal_id, _buyer_init, _seller_init, _, _ = await _create_deal(client)
    admin_init = await _make_staff(client, tg_id=5301, username="ch_admin", role="admin")
    arb_init = await _make_staff(client, tg_id=5302, username="ch_arb", role="arbiter")

    # Staff-allowed terminal states: 201 for both admin and arbiter.
    for st in (DealStatus.resolved_for_buyer, DealStatus.resolved_for_seller):
        await _set_status(deal_id, st)
        for label, init in (("admin", admin_init), ("arbiter", arb_init)):
            resp = await client.post(
                f"/api/deals/{deal_id}/messages",
                json={"text": f"verdict in {st.value}", "attachments": []},
                headers=auth_headers(init),
            )
            assert resp.status_code == 201, f"{label}@{st.value}: {resp.status_code} {resp.text}"

    # Staff-blocked terminal states: 409 for both.
    for st in (
        DealStatus.completed,
        DealStatus.cancelled,
        DealStatus.cancelled_for_inactivity,
    ):
        await _set_status(deal_id, st)
        for label, init in (("admin", admin_init), ("arbiter", arb_init)):
            resp = await client.post(
                f"/api/deals/{deal_id}/messages",
                json={"text": f"closing word in {st.value}", "attachments": []},
                headers=auth_headers(init),
            )
            assert resp.status_code == 409, f"{label}@{st.value}: {resp.status_code} {resp.text}"


async def test_messages_still_allowed_in_active_statuses(client):
    """Comment 37 sanity — the block only applies to terminal states.
    ``pending_confirmation``, ``in_progress``, ``arbitration``,
    ``pending_cancellation`` all keep the chat open for the parties
    so the legitimate happy path doesn't regress."""
    from backend.app.models import DealStatus

    deal_id, buyer_init, _seller_init, _, _ = await _create_deal(client)

    for st in (
        DealStatus.pending_confirmation,
        DealStatus.in_progress,
        DealStatus.arbitration,
        DealStatus.pending_cancellation,
    ):
        await _set_status(deal_id, st)
        resp = await client.post(
            f"/api/deals/{deal_id}/messages",
            json={"text": f"alive in {st.value}", "attachments": []},
            headers=auth_headers(buyer_init),
        )
        assert resp.status_code == 201, f"{st.value}: {resp.status_code} {resp.text}"
