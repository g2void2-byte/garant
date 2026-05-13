"""WebSocket live-notification fan-out (validates the B1 fix).

Before the fix, ``routers/ws.py`` registered the socket under the Telegram
``user_id`` from initData while ``notifier.push`` fanned out under the
internal ``User.id``. The two never matched, so this test would never
see an event arrive on the WS within the timeout.
"""

from __future__ import annotations

import asyncio
import json
from urllib.parse import quote

import websockets

from tests.helpers import get_user_id_by_tg, signed_init_data


async def test_ws_receives_notification_for_authenticated_user(ws_server):
    from backend.app.db import async_session
    from backend.app.models import NotificationType
    from backend.app.notifier import push

    init_data = signed_init_data(4001, "alice4")
    url = f"ws://127.0.0.1:{ws_server}/ws/notifications?initData={quote(init_data)}"

    async with websockets.connect(url, open_timeout=5) as ws:
        # The WS handler creates the user on connect.
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


async def test_ws_rejects_missing_init_data(ws_server):
    url = f"ws://127.0.0.1:{ws_server}/ws/notifications"
    try:
        async with websockets.connect(url, open_timeout=5):
            raise AssertionError("WS should have been rejected")
    except websockets.exceptions.InvalidStatusCode as exc:
        # FastAPI returns 403 for a rejected handshake before .accept().
        assert exc.status_code in (401, 403, 4001)
    except websockets.exceptions.ConnectionClosed:
        # Some websockets versions surface the rejection as a close.
        pass
