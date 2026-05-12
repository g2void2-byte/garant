from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from utils.database.extras import WebDB
from utils.database.models import Users
from utils.notifier import notifier
from webapp.backend.security import InitDataError, verify_init_data

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/notifications")
async def notifications_ws(ws: WebSocket) -> None:
    init_data = ws.query_params.get("initData") or ws.headers.get("x-init-data") or ""
    try:
        parsed = verify_init_data(init_data)
    except InitDataError as exc:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(exc))
        return

    user = Users.get_or_none(Users.user_id == parsed.user.id)
    if user is None:
        user = Users.create(user_id=parsed.user.id, username=parsed.user.username)
    username = user.username

    await ws.accept()
    WebDB().touch_online(username)
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    await notifier.subscribe(username, queue)

    async def keepalive() -> None:
        try:
            while True:
                await asyncio.sleep(25)
                await ws.send_json({"event": "ping"})
        except Exception:
            return

    keepalive_task = asyncio.create_task(keepalive())

    try:
        while True:
            event = await queue.get()
            await ws.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WS notifications loop crashed")
    finally:
        keepalive_task.cancel()
        await notifier.unsubscribe(username, queue)
