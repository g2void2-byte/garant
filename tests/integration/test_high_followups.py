"""Regression tests for the High-severity findings in the May review.

* **H1** ``ws_manager.invalidate_user`` — admin ``invalidate-sessions``
  must close every active WebSocket for the target user so the
  notifications channel doesn't keep streaming to a now-untrusted
  device until the connection times out on its own.
* **H3** ``get_current_user`` ``last_login_at`` / ``login_count``
  debounce — consecutive API calls must not generate a Postgres UPDATE
  on every request.

H2 lives in the frontend (PinGate reacts to a 401 from the server) and
is covered by the matching frontend test in
``frontend/src/__tests__/PinGate.test.tsx`` once the JS test runner is
wired up; for now the backend's job is to keep returning the precise
``detail`` strings (``"PIN-сессия отозвана"`` etc.) that the new ky
``beforeError`` interceptor matches on. The shape is already locked in
by ``test_security_audit.test_invalidate_sessions_revokes_active_pin_token``.
"""

from __future__ import annotations

import asyncio
import json

import websockets
from sqlalchemy import select

from tests.helpers import auth_headers, setup_pin, signed_init_data, with_totp


async def _connect_and_auth(ws_server: int, init_data: str):
    url = f"ws://127.0.0.1:{ws_server}/ws/notifications"
    ws = await websockets.connect(url, open_timeout=5)
    await ws.send(json.dumps({"type": "auth", "init_data": init_data}))
    ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
    assert ack == {"type": "auth", "ok": True}, ack
    return ws


async def test_invalidate_sessions_closes_active_websocket(client, ws_server):
    """H1 — POST /api/admin/users/{id}/invalidate-sessions must close
    every active WS for the target. Without the fix the socket happily
    survives and keeps receiving fan-out events.
    """
    from backend.app.db import async_session
    from backend.app.models import User

    # Victim opens an authenticated socket.
    victim_init = signed_init_data(8101, "victim8101")
    await client.get("/api/me", headers=auth_headers(victim_init))
    ws = await _connect_and_auth(ws_server, victim_init)

    # Bootstrap admin and call invalidate-sessions on the victim.
    admin_init = signed_init_data(8102, "admin8102")
    await client.get("/api/me", headers=auth_headers(admin_init))
    async with async_session() as session:
        admin = (await session.execute(select(User).where(User.tg_user_id == 8102))).scalar_one()
        admin.is_admin = True
        target = (await session.execute(select(User).where(User.tg_user_id == 8101))).scalar_one()
        target_id = target.id
        await session.commit()

    try:
        resp = await client.post(
            f"/api/admin/users/{target_id}/invalidate-sessions",
            json={"reason": "lost phone"},
            headers=with_totp(auth_headers(admin_init)),
        )
        assert resp.status_code == 200, resp.text

        # The socket must observe a close. ``_audit_and_notify`` also
        # fans out a ``system`` notification before the close arrives,
        # so we drain any in-flight frames until ``ConnectionClosed``
        # bubbles up (or we time out — which would be the bug).
        close_seen = False
        deadline = asyncio.get_event_loop().time() + 3.0
        while not close_seen:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise AssertionError("WS did not close after invalidate-sessions")
            try:
                await asyncio.wait_for(ws.recv(), timeout=remaining)
            except websockets.exceptions.ConnectionClosed as exc:
                assert exc.code == 4001, (exc.code, exc.reason)
                assert "revoked" in str(exc.reason).lower()
                close_seen = True
    finally:
        try:
            await ws.close()
        except Exception:
            pass


async def test_get_current_user_debounces_last_login_writes(client):
    """H3 — repeated /api/me calls must NOT bump ``login_count`` on
    every request. Two calls in quick succession share the same
    ``last_login_at`` and increment the counter once at most.
    """
    from backend.app.db import async_session
    from backend.app.models import User

    init = signed_init_data(8201, "debounce8201")

    # First call creates the row (login_count = 1 on insert path).
    r1 = await client.get("/api/me", headers=auth_headers(init))
    assert r1.status_code == 200, r1.text

    async with async_session() as session:
        u1 = (await session.execute(select(User).where(User.tg_user_id == 8201))).scalar_one()
        login_count_after_first = u1.login_count
        last_login_after_first = u1.last_login_at

    # Five more calls in immediate succession must not touch the row.
    for _ in range(5):
        r = await client.get("/api/me", headers=auth_headers(init))
        assert r.status_code == 200, r.text

    async with async_session() as session:
        u2 = (await session.execute(select(User).where(User.tg_user_id == 8201))).scalar_one()
        assert u2.login_count == login_count_after_first, (
            f"login_count bumped from {login_count_after_first} to {u2.login_count}"
        )
        assert u2.last_login_at == last_login_after_first, (
            f"last_login_at changed from {last_login_after_first} to {u2.last_login_at}"
        )


async def test_get_current_user_updates_after_debounce_window(client, monkeypatch):
    """H3 follow-up — once enough time has passed (debounce window
    elapsed), the next call DOES advance ``last_login_at``. We patch
    the module-level constant down to zero so the test doesn't sleep
    for five minutes.
    """
    from datetime import timedelta

    from backend.app import deps
    from backend.app.db import async_session
    from backend.app.models import User

    monkeypatch.setattr(deps, "_LAST_LOGIN_DEBOUNCE", timedelta(seconds=0))

    init = signed_init_data(8202, "debounce8202")
    await client.get("/api/me", headers=auth_headers(init))

    async with async_session() as session:
        u1 = (await session.execute(select(User).where(User.tg_user_id == 8202))).scalar_one()
        count_before = u1.login_count

    await client.get("/api/me", headers=auth_headers(init))

    async with async_session() as session:
        u2 = (await session.execute(select(User).where(User.tg_user_id == 8202))).scalar_one()
        assert u2.login_count == count_before + 1


async def test_pin_session_invalid_detail_strings_are_stable(client):
    """H2 contract test — the frontend's ``beforeError`` interceptor
    matches on the ``code`` field of the structured error that
    ``require_pin_session`` raises. If the codes ever drift, PinGate
    stops reacting to server-side invalidation. This test pins the
    codes and detail strings.
    """
    init = signed_init_data(8301, "pin_contract")
    await setup_pin(client, init)

    # Hit a PIN-gated endpoint with NO X-Pin-Token header.
    resp = await client.post(
        "/api/account/transfer/cancel",
        headers=auth_headers(init),
    )
    assert resp.status_code == 401
    detail = resp.json().get("detail")
    assert detail["code"] == "pin_session_missing"
    assert detail["detail"] == "PIN-сессия отсутствует"

    # Hit with a garbage token.
    resp = await client.post(
        "/api/account/transfer/cancel",
        headers={**auth_headers(init), "X-Pin-Token": "not-a-jwt"},
    )
    assert resp.status_code == 401
    detail = resp.json().get("detail")
    assert detail["code"] == "pin_session_invalid"
    assert detail["detail"] == "PIN-сессия недействительна"
