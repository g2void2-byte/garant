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

    # ``notifier.push`` fans out events keyed by the internal ``User.id``,
    # so we must register the socket under the same id (not the Telegram
    # ``tg_user_id`` exposed in initData) — otherwise the WS channel is a
    # silent black hole.
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.tg_user_id == tg_user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                tg_user_id=tg_user_id,
                username=tg_user.get("username"),
                display_name=tg_user.get("first_name", ""),
                photo_url=tg_user.get("photo_url"),
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        user_id = user.id

    await manager.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
    except Exception:
        manager.disconnect(user_id, websocket)
