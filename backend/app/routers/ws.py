"""Notification WebSocket endpoint.

The legacy entry point read ``initData`` from the query string —
``ws://.../ws/notifications?initData=<HMAC-signed Telegram blob>``.
That value lands in every upstream access log (nginx, ingress, CDN,
APM probes), so anybody with log access can replay it for the rest of
the ``auth_date`` window. The audit flagged this as a Medium-severity
PII sink.

The fix is the standard "auth via first message" pattern:
  1. Server accepts the socket so the client can stream a body.
  2. Client sends ``{"type":"auth","init_data":"<…>"}`` as its first
     frame.
  3. Server verifies the blob; on failure it closes with code 4001.
  4. On success the server ACKs with ``{"type":"auth","ok":true}`` and
     proceeds to the normal message loop.

A bounded ``receive_text`` timeout (``WS_AUTH_TIMEOUT_SECONDS``) and
payload-size cap (``WS_AUTH_MAX_BYTES``) keep the endpoint from being
used as a slow-loris / memory-amplifier vector.
"""

from __future__ import annotations

import asyncio
import json
import logging
from urllib.parse import parse_qs

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ..db import async_session
from ..deps import _normalise_language_code
from ..models import User
from ..security import InitDataError, verify_init_data
from ..ws import manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ws"])

# Tunables. Kept module-level so tests can patch them.
WS_AUTH_TIMEOUT_SECONDS = 5.0
WS_AUTH_MAX_BYTES = 8 * 1024  # initData is normally well under 2 KB.


async def _read_auth_frame(websocket: WebSocket) -> str | None:
    """Read the client's first frame and extract ``init_data``.

    Returns the raw initData string on success, or ``None`` after
    closing the socket with the appropriate ``4001`` reason.
    """
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=WS_AUTH_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        await websocket.close(code=4001, reason="Auth timeout")
        return None
    except WebSocketDisconnect:
        return None

    if len(raw) > WS_AUTH_MAX_BYTES:
        await websocket.close(code=4001, reason="Auth payload too large")
        return None

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        await websocket.close(code=4001, reason="Auth: invalid JSON")
        return None

    if not isinstance(payload, dict) or payload.get("type") != "auth":
        await websocket.close(code=4001, reason="Auth: bad envelope")
        return None

    init_data = payload.get("init_data")
    if not isinstance(init_data, str) or not init_data:
        await websocket.close(code=4001, reason="Auth: missing init_data")
        return None

    return init_data


def _parse_auth_date(init_data: str) -> int | None:
    """Extract ``auth_date`` from a verified initData blob.

    Returns ``None`` if the field is missing or non-numeric — the
    age-check reaper just skips sockets without an ``auth_date`` so
    older clients / unsigned-dev-data don't get spuriously closed.
    """
    try:
        parsed = parse_qs(init_data, keep_blank_values=True)
        raw = parsed.get("auth_date", [None])[0]
        if raw is None:
            return None
        return int(raw)
    except (ValueError, TypeError):
        return None


@router.websocket("/ws/notifications")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    init_data = await _read_auth_frame(websocket)
    if init_data is None:
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
        result = await session.execute(select(User).where(User.tg_user_id == tg_user_id))
        user = result.scalar_one_or_none()
        if user is None:
            # A-6 — capture the Telegram client locale on the WS first-touch
            # path too, so a brand-new user whose very first hit is the
            # notifications socket still lands in the right broadcast
            # cohort (see ``deps._normalise_language_code``).
            user = User(
                tg_user_id=tg_user_id,
                username=tg_user.get("username"),
                display_name=tg_user.get("first_name", ""),
                photo_url=tg_user.get("photo_url"),
                language_code=_normalise_language_code(tg_user.get("language_code")),
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        user_id = user.id

    # ACK so the client knows the channel is live and can flip its UI
    # state (badges, "connected" indicator, etc.).
    try:
        await websocket.send_text(json.dumps({"type": "auth", "ok": True}))
    except WebSocketDisconnect:
        return

    # Pass ``auth_date`` to the manager so the per-socket age-check
    # reaper can evict sockets whose initData has aged past the cap
    # (see backend/app/ws.py: WS_MAX_AGE_SECONDS).
    await manager.connect(user_id, websocket, auth_date_epoch=_parse_auth_date(init_data))

    # Comment 38: heartbeat loop — keeps NAT/proxy connections alive
    # and lets the client detect silent drops.
    from ..config import settings as app_settings

    hb_interval = app_settings.ws_heartbeat_interval_seconds

    async def _heartbeat() -> None:
        try:
            while True:
                await asyncio.sleep(hb_interval)
                await manager.send_heartbeat(websocket)
        except asyncio.CancelledError:
            pass

    hb_task = asyncio.create_task(_heartbeat())

    try:
        while True:
            await websocket.receive_text()
            # Comment 38: inbound rate check.
            if not manager.check_recv_rate(websocket):
                await websocket.close(code=4008, reason="Rate limit exceeded")
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        # V11-L-15 — log unexpected message-loop exits (broken pipe,
        # protocol error, sudden TCP reset, …) with structured fields
        # so the JSON logger downstream (Loki / Sentry) can pivot on
        # the disconnect reason without scraping the message body.
        # Pre-fix this was a bare ``except Exception: pass``, so any
        # exception other than ``WebSocketDisconnect`` was silently
        # swallowed and the only signal an operator had was the
        # connection count quietly drifting.
        logger.warning(
            "ws message loop exited with unexpected exception",
            extra={
                "event": "ws.message_loop.unexpected_exception",
                "user_id": user_id,
            },
            exc_info=True,
        )
    finally:
        hb_task.cancel()
        manager.disconnect(user_id, websocket)
