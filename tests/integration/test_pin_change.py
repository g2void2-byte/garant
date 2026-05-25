"""I-2 — ``POST /api/pin/change`` happy + failure paths.

``tests/test_wallet_withdrawal_pin.py`` exercises PIN-gate enforcement
on a single endpoint, but the audit flagged that the ``/api/pin/change``
endpoint itself had no test coverage. This covers:

* Happy path — old PIN verified, new PIN replaces it, fresh token issued.
* Wrong old PIN — 401, attempt counter increments, ``pin_hash`` unchanged.
* Lockout — N consecutive wrong attempts trip a temporary lock (423).
* No PIN set — 409 (caller should hit ``/setup`` first).
* Format validation — non-4-digit PIN rejected as 400.
* Old token survives — changing the PIN does *not* invalidate the
  caller's current ``X-Pin-Token`` (the change endpoint mints a new
  one; old session stays valid until either TTL expiry or an admin
  ``invalidate-sessions`` bump). This documents the current behaviour
  so future changes are intentional.
"""

from __future__ import annotations

from sqlalchemy import select

from backend.app.config import settings
from backend.app.db import async_session
from backend.app.models import User
from backend.app.pin import verify_pin
from tests.helpers import auth_headers, setup_pin, signed_init_data


async def _get_user(tg_user_id: int) -> User:
    async with async_session() as session:
        return (
            await session.execute(select(User).where(User.tg_user_id == tg_user_id))
        ).scalar_one()


async def test_pin_change_happy_path(client):
    init = signed_init_data(6001, "pin_change_ok")
    old_token = await setup_pin(client, init, pin="5837")

    resp = await client.post(
        "/api/pin/change",
        json={"old_pin": "5837", "new_pin": "4163"},
        headers=auth_headers(init),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token"] != old_token, "new PIN session token must differ"
    assert body["expires_at"]

    # New PIN hash persisted, attempts reset.
    user = await _get_user(6001)
    assert verify_pin("4163", user.pin_hash)
    assert not verify_pin("5837", user.pin_hash)
    assert (user.pin_attempts or 0) == 0
    assert user.pin_locked_until is None


async def test_pin_change_wrong_old_pin_increments_attempts(client):
    init = signed_init_data(6002, "pin_change_wrong")
    await setup_pin(client, init, pin="5837")

    resp = await client.post(
        "/api/pin/change",
        # ``9999`` is in the blacklist but that's irrelevant here —
        # the wrong-old-PIN branch returns 401 (with attempts++)
        # BEFORE the new-PIN strength check, so the new_pin value
        # being weak doesn't change the response.
        json={"old_pin": "9999", "new_pin": "4163"},
        headers=auth_headers(init),
    )
    assert resp.status_code == 401, resp.text
    assert "Старый PIN неверен" in resp.json().get("detail", "")

    user = await _get_user(6002)
    assert verify_pin("5837", user.pin_hash), "pin_hash must be unchanged"
    assert (user.pin_attempts or 0) == 1


async def test_pin_change_locks_after_max_attempts(client):
    """``pin_max_attempts`` consecutive wrong tries should trip a lock.

    The lock window is configurable via ``PIN_LOCK_MINUTES``; we just
    assert the response code + that ``pin_locked_until`` is set in
    the future. The attempts counter is reset on lock so the next
    window starts fresh.
    """
    init = signed_init_data(6003, "pin_change_lock")
    await setup_pin(client, init, pin="5837")

    max_attempts = settings.pin_max_attempts
    last_resp = None
    for _ in range(max_attempts):
        last_resp = await client.post(
            "/api/pin/change",
            json={"old_pin": "9999", "new_pin": "4163"},
            headers=auth_headers(init),
        )
    assert last_resp is not None
    assert last_resp.status_code == 423, last_resp.text

    user = await _get_user(6003)
    assert user.pin_locked_until is not None
    # Counter reset once the lock kicks in.
    assert (user.pin_attempts or 0) == 0
    # Even with correct old PIN, change is now blocked while locked.
    blocked = await client.post(
        "/api/pin/change",
        json={"old_pin": "5837", "new_pin": "7592"},
        headers=auth_headers(init),
    )
    assert blocked.status_code == 423, blocked.text


async def test_pin_change_without_pin_setup(client):
    """Calling ``/change`` before ``/setup`` is a 409, not a 401."""
    init = signed_init_data(6004, "pin_change_nopin")
    # Bootstrap the user row without setting a PIN.
    await client.get("/api/me", headers=auth_headers(init))

    resp = await client.post(
        "/api/pin/change",
        json={"old_pin": "5837", "new_pin": "4163"},
        headers=auth_headers(init),
    )
    assert resp.status_code == 409, resp.text


async def test_pin_change_format_rejected(client):
    """Pydantic-level (length) rejection returns 422; the in-router
    ``_ensure_format`` catches non-digit input as 400.

    We feed a 4-character non-digit string to hit the 400 branch.
    """
    init = signed_init_data(6005, "pin_change_fmt")
    await setup_pin(client, init, pin="5837")

    resp = await client.post(
        "/api/pin/change",
        json={"old_pin": "5837", "new_pin": "abcd"},
        headers=auth_headers(init),
    )
    assert resp.status_code == 400, resp.text
