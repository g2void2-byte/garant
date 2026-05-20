"""WebSocket live-notification fan-out + first-message auth.

The endpoint authenticates by reading a ``{"type":"auth","init_data":"…"}``
frame after ``accept()`` (initData no longer rides in the URL query
string — see the audit Medium #8 fix). These tests cover both the happy
path (auth → ACK → push fan-out arrives) and the negative paths
(missing/invalid init_data, malformed envelope, non-JSON, timeout).
"""

from __future__ import annotations

import asyncio
import json

import websockets

from tests.helpers import get_user_id_by_tg, signed_init_data


async def _connect_and_auth(ws_server: int, init_data: str):
    """Open a socket and complete the first-message handshake.

    Returns the open ``websockets`` client once the server ACK has
    arrived. Raises if the handshake doesn't complete.
    """
    url = f"ws://127.0.0.1:{ws_server}/ws/notifications"
    ws = await websockets.connect(url, open_timeout=5)
    await ws.send(json.dumps({"type": "auth", "init_data": init_data}))
    ack_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
    ack = json.loads(ack_raw)
    assert ack == {"type": "auth", "ok": True}, ack
    return ws


async def test_ws_receives_notification_for_authenticated_user(ws_server):
    """Happy path: first-message auth + push fan-out keyed by User.id."""
    from backend.app.db import async_session
    from backend.app.models import NotificationType
    from backend.app.notifier import push

    init_data = signed_init_data(4001, "alice4")
    ws = await _connect_and_auth(ws_server, init_data)
    try:
        async with async_session() as session:
            user_id = await get_user_id_by_tg(session, 4001)
            await push(
                session,
                user_id,
                NotificationType.deals,
                "Test title",
                "Test body",
                {"deal_id": 42},
            )

        msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
        event = json.loads(msg)
        assert event["event"] == "notification"
        assert event["data"]["title"] == "Test title"
        assert event["data"]["body"] == "Test body"
        assert event["data"]["payload"] == {"deal_id": 42}
    finally:
        await ws.close()


async def test_ws_rejects_missing_init_data(ws_server):
    """An auth frame without ``init_data`` is rejected with 4001."""
    url = f"ws://127.0.0.1:{ws_server}/ws/notifications"
    async with websockets.connect(url, open_timeout=5) as ws:
        await ws.send(json.dumps({"type": "auth", "init_data": ""}))
        try:
            await asyncio.wait_for(ws.recv(), timeout=2.0)
            raise AssertionError("expected close, got a frame")
        except websockets.exceptions.ConnectionClosed as exc:
            assert exc.code == 4001
            assert "init_data" in str(exc.reason).lower()


async def test_ws_rejects_bad_envelope(ws_server):
    """Frames whose ``type`` isn't ``auth`` are rejected with 4001."""
    url = f"ws://127.0.0.1:{ws_server}/ws/notifications"
    async with websockets.connect(url, open_timeout=5) as ws:
        await ws.send(json.dumps({"type": "ping"}))
        try:
            await asyncio.wait_for(ws.recv(), timeout=2.0)
            raise AssertionError("expected close, got a frame")
        except websockets.exceptions.ConnectionClosed as exc:
            assert exc.code == 4001
            assert "envelope" in str(exc.reason).lower()


async def test_ws_rejects_non_json(ws_server):
    """Garbage as the first frame is rejected with 4001."""
    url = f"ws://127.0.0.1:{ws_server}/ws/notifications"
    async with websockets.connect(url, open_timeout=5) as ws:
        await ws.send("not-json-at-all")
        try:
            await asyncio.wait_for(ws.recv(), timeout=2.0)
            raise AssertionError("expected close, got a frame")
        except websockets.exceptions.ConnectionClosed as exc:
            assert exc.code == 4001
            assert "json" in str(exc.reason).lower()


async def test_ws_rejects_forged_init_data(ws_server):
    """An init_data string with a bad HMAC is rejected with 4001."""
    url = f"ws://127.0.0.1:{ws_server}/ws/notifications"
    async with websockets.connect(url, open_timeout=5) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "auth",
                    # Well-formed querystring, invalid signature.
                    "init_data": (
                        "user=%7B%22id%22%3A1%2C%22first_name%22%3A%22x%22%7D"
                        "&auth_date=1700000000&hash=deadbeef"
                    ),
                }
            )
        )
        try:
            await asyncio.wait_for(ws.recv(), timeout=2.0)
            raise AssertionError("expected close, got a frame")
        except websockets.exceptions.ConnectionClosed as exc:
            assert exc.code == 4001


async def test_ws_auth_times_out(ws_server, monkeypatch):
    """If the client never sends an auth frame, the server closes."""
    import backend.app.routers.ws as ws_router

    monkeypatch.setattr(ws_router, "WS_AUTH_TIMEOUT_SECONDS", 0.5)

    url = f"ws://127.0.0.1:{ws_server}/ws/notifications"
    async with websockets.connect(url, open_timeout=5) as ws:
        try:
            await asyncio.wait_for(ws.recv(), timeout=3.0)
            raise AssertionError("expected close, got a frame")
        except websockets.exceptions.ConnectionClosed as exc:
            assert exc.code == 4001
            assert "timeout" in str(exc.reason).lower()
