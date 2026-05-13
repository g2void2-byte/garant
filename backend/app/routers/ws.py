from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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

    user_id = tg_user.get("id")
    if not user_id:
        await websocket.close(code=4001, reason="No user id")
        return

    await manager.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
    except Exception:
        manager.disconnect(user_id, websocket)
