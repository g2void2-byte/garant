from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ..db import async_session
from ..models import User
from ..security import InitDataError, verify_init_data
from ..ws import manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ws"])


@router.websocket("/ws/notifications")
async def websocket_endpoint(websocket: WebSocket):
    init_data = websocket.query_params.get("initData", "")
    if not init_data:
        await websocket.close(code=4001, reason="Missing initData")
        return

    try:
        tg_user = verify_init_data(init_data)
    except InitDataError as e:
        await websocket.close(code=4001, reason=str(e))
        return

    tg_user_id = tg_user.get("id")
    if not tg_user_id:
        await websocket.close(code=4001, reason="No user id")
        return

    # Map Telegram id → internal User.id; ``notifier.push`` and
    # ``services_chat`` route by internal id so the WS must register
    # under that key. Skip the WS if the user has never hit the API.
    async with async_session() as session:
        user = (
            await session.execute(
                select(User).where(User.tg_user_id == tg_user_id)
            )
        ).scalar_one_or_none()
    if user is None:
        await websocket.close(code=4001, reason="Unknown user")
        return
    internal_id = user.id

    await manager.connect(internal_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(internal_id, websocket)
    except Exception:
        manager.disconnect(internal_id, websocket)
