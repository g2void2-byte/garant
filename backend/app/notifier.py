from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Notification, NotificationType
from .ws import manager

logger = logging.getLogger(__name__)


async def push(
    session: AsyncSession,
    recipient_id: int,
    type_: NotificationType,
    title: str,
    body: str = "",
    payload: dict[str, Any] | None = None,
) -> Notification:
    notif = Notification(
        recipient_id=recipient_id,
        type=type_,
        title=title,
        body=body,
        payload=json.dumps(payload) if payload else None,
    )
    session.add(notif)
    await session.commit()
    await session.refresh(notif)

    await manager.send_to_user(recipient_id, {
        "event": "notification",
        "data": {
            "id": notif.id,
            "type": notif.type.value,
            "title": notif.title,
            "body": notif.body,
            "payload": payload,
            "is_read": False,
        },
    })

    return notif
