"""Audit "simple flag" follow-ups — see the audit_v10 dump.

Covers the behavioural changes that need a real DB / HTTP / WS setup:

* **H-3** — ``/ws/notifications`` refuses to keep the socket open for a
  banned / frozen account; the existing REST surface already 403s.
* **L-2** — ``_ensure_not_last_admin`` takes a row-level lock on the
  admin set, so two parallel demotes can't both observe ``count >= 2``
  and end up dropping the count to zero.
* **L-10** — ``confirm_transfer`` bumps both ``pin_session_epoch`` and
  ``totp_session_epoch`` on the source row, invalidating any PIN /
  TOTP session token that was issued under the previous identity.
"""

from __future__ import annotations

import asyncio
import json

import websockets

from tests.helpers import (
    auth_headers,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)

# ── H-3 — WS refuses locked-out account ───────────────────────────


async def test_ws_refuses_banned_user(client, ws_server):
    """A user with ``is_banned=True`` cannot complete the WS auth
    handshake — the server closes the socket with code 4003.
    """
    from backend.app.db import async_session
    from backend.app.models import User

    init_data = signed_init_data(99001, "ws_banned_user")

    # Bootstrap the row via REST so we can flip the ``is_banned`` flag
    # without poking the model defaults. The ``client`` fixture and
    # the ``ws_server`` fixture share the same ``app`` (and same DB),
    # so a row created here is visible to the uvicorn-backed WS.
    resp = await client.get("/api/me", headers=auth_headers(init_data))
    assert resp.status_code == 200, resp.text

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 99001)
        user = await session.get(User, user_id)
        assert user is not None
        user.is_banned = True
        user.ban_reason = "test ban"
        await session.commit()

    url = f"ws://127.0.0.1:{ws_server}/ws/notifications"
    async with websockets.connect(url, open_timeout=5) as ws:
        await ws.send(json.dumps({"type": "auth", "init_data": init_data}))
        try:
            await asyncio.wait_for(ws.recv(), timeout=3.0)
            raise AssertionError("expected close, got a frame")
        except websockets.exceptions.ConnectionClosed as exc:
            assert exc.code == 4003, exc


async def test_ws_refuses_frozen_user(client, ws_server):
    """Same as ``test_ws_refuses_banned_user`` but for the freeze branch."""
    from backend.app.db import async_session
    from backend.app.models import User

    init_data = signed_init_data(99002, "ws_frozen_user")

    resp = await client.get("/api/me", headers=auth_headers(init_data))
    assert resp.status_code == 200, resp.text

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 99002)
        user = await session.get(User, user_id)
        assert user is not None
        user.is_frozen = True
        user.freeze_reason = "test freeze"
        await session.commit()

    url = f"ws://127.0.0.1:{ws_server}/ws/notifications"
    async with websockets.connect(url, open_timeout=5) as ws:
        await ws.send(json.dumps({"type": "auth", "init_data": init_data}))
        try:
            await asyncio.wait_for(ws.recv(), timeout=3.0)
            raise AssertionError("expected close, got a frame")
        except websockets.exceptions.ConnectionClosed as exc:
            assert exc.code == 4003, exc


# ── L-10 — confirm_transfer bumps the session epochs ───────────────


async def test_confirm_transfer_bumps_session_epochs(client):
    """Both ``pin_session_epoch`` and ``totp_session_epoch`` must be
    incremented after a successful ``confirm_transfer`` so any PIN /
    TOTP token issued under the previous identity stops working.
    """
    from backend.app.db import async_session
    from backend.app.models import User
    from backend.app.services_account import issue_code

    source_init = signed_init_data(98001, "src_epochs")
    target_init = signed_init_data(98002, "tgt_epochs")

    # Bootstrap both rows.
    await setup_pin(client, source_init)
    resp = await client.get("/api/me", headers=auth_headers(target_init))
    assert resp.status_code == 200

    # Snapshot pre-transfer epochs.
    async with async_session() as session:
        src_id = await get_user_id_by_tg(session, 98001)
        src = await session.get(User, src_id)
        assert src is not None
        pin_before = int(src.pin_session_epoch or 0)
        totp_before = int(src.totp_session_epoch or 0)
        code, _ = await issue_code(session, src)

    # Confirm from the target side.
    resp = await client.post(
        "/api/account/transfer/confirm",
        json={"code": code},
        headers=auth_headers(target_init),
    )
    assert resp.status_code == 200, resp.text

    # The source row now has the target's tg_user_id; both epoch
    # columns must have been bumped exactly once.
    async with async_session() as session:
        src = await session.get(User, src_id)
        assert src is not None
        assert src.tg_user_id == 98002
        assert int(src.pin_session_epoch or 0) == pin_before + 1
        assert int(src.totp_session_epoch or 0) == totp_before + 1


# ── L-2 — last-admin guard takes the row-lock before counting ───────


async def test_last_admin_guard_uses_for_update(client):
    """The admin-set lock is observable via the SQL it emits. We assert
    the helper executes a ``SELECT ... FOR UPDATE`` against the
    ``users.is_admin = true`` set instead of an unlocked ``COUNT(*)``.
    """
    from sqlalchemy import event

    from backend.app.db import async_session
    from backend.app.models import User
    from backend.app.routers.admin.users import _ensure_not_last_admin

    async with async_session() as session:
        # Seed two admins so the guard takes the "more than one" branch.
        admin_a = User(tg_user_id=70001, username="adm_a", display_name="A", is_admin=True)
        admin_b = User(tg_user_id=70002, username="adm_b", display_name="B", is_admin=True)
        session.add_all([admin_a, admin_b])
        await session.commit()
        target = admin_a

        statements: list[str] = []

        sync_conn = await session.connection()

        def _capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        sync_engine = sync_conn.sync_engine

        event.listen(sync_engine, "before_cursor_execute", _capture)
        try:
            await _ensure_not_last_admin(session, target)
        finally:
            event.remove(sync_engine, "before_cursor_execute", _capture)

    # At least one statement must request a row-lock against ``users``.
    locked = [s for s in statements if "FOR UPDATE" in s.upper() and "USERS" in s.upper()]
    assert locked, statements
