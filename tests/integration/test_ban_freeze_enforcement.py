"""I-1 — runtime enforcement of ``is_banned`` / ``is_frozen`` flags.

``test_admin_users.py`` already covers the admin endpoints that *set*
these flags. What was missing was a check that the flags actually
take effect at the auth layer: ``deps.get_current_user`` raises 403
when either flag is on, but no test exercised that path end-to-end
for a non-admin endpoint.

If someone accidentally removes the guard in ``deps.py``, the existing
suite stays green — these tests fail loudly instead.
"""

from __future__ import annotations

from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import User
from tests.helpers import auth_headers, signed_init_data


async def _set_user_flag(tg_user_id: int, *, banned: bool = False, frozen: bool = False) -> None:
    """Toggle ``is_banned`` / ``is_frozen`` directly via the ORM.

    We bypass the admin endpoint here on purpose: the goal is to test
    the enforcement layer in isolation, not the admin POST handler
    (which has its own coverage).
    """
    async with async_session() as session:
        user = (
            await session.execute(select(User).where(User.tg_user_id == tg_user_id))
        ).scalar_one()
        if banned:
            user.is_banned = True
            user.ban_reason = "test"
        if frozen:
            user.is_frozen = True
            user.freeze_reason = "test"
        await session.commit()


async def _bootstrap_user(client, tg_user_id: int, username: str) -> None:
    """Hit any auth-required endpoint so the ``User`` row gets created."""
    init = signed_init_data(tg_user_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text


async def test_banned_user_blocked_on_authenticated_endpoint(client):
    """Precondition: user can call ``/api/me``. After ban → 403."""
    init = signed_init_data(5001, "ban_target")
    await _bootstrap_user(client, 5001, "ban_target")

    # Sanity: still authorised before the flag is set.
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200

    await _set_user_flag(5001, banned=True)

    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 403, resp.text
    # Item 24 — the 403 now carries a structured payload so the
    # frontend can route to the dedicated ban gate.
    detail = resp.json()["detail"]
    assert detail["code"] == "banned"
    assert "заблокирован" in detail["message"]
    assert detail["reason"] == "test"
    # ``admin_username`` falls through when no admin has a username yet
    # (test environment has none) — just assert the key is present.
    assert "admin_username" in detail


async def test_frozen_user_blocked_on_authenticated_endpoint(client):
    """``is_frozen`` triggers a distinct 403 from ``is_banned``.

    Both end up as 403 but with different ``detail`` strings — the
    frontend uses the detail to render the right toast.
    """
    init = signed_init_data(5002, "freeze_target")
    await _bootstrap_user(client, 5002, "freeze_target")

    await _set_user_flag(5002, frozen=True)

    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "frozen"
    assert "заморожен" in detail["message"]
    assert detail["reason"] == "test"


async def test_banned_user_cannot_write(client):
    """Writes — not just reads — must be refused.

    Picks ``POST /api/services`` as a representative non-admin write
    endpoint. If the guard ever moves to be read-only this test
    catches the regression.
    """
    init = signed_init_data(5003, "ban_writer")
    await _bootstrap_user(client, 5003, "ban_writer")

    await _set_user_flag(5003, banned=True)

    resp = await client.post(
        "/api/services",
        json={
            "category_slug": "test",
            "title": "test",
            "description": "test",
            "price": 10.0,
        },
        headers=auth_headers(init),
    )
    # ``get_current_user`` short-circuits before the endpoint runs, so
    # we expect 403 regardless of body validity / whether the
    # ``test`` category actually exists.
    assert resp.status_code == 403, resp.text


async def test_unbanned_user_can_resume(client):
    """After ``is_banned`` is flipped off, the user is unblocked again.

    Confirms there's no extra session/caching layer that would
    persist the rejection past the flag change.
    """
    init = signed_init_data(5004, "ban_clear")
    await _bootstrap_user(client, 5004, "ban_clear")

    await _set_user_flag(5004, banned=True)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 403

    async with async_session() as session:
        user = (await session.execute(select(User).where(User.tg_user_id == 5004))).scalar_one()
        user.is_banned = False
        user.ban_reason = None
        await session.commit()

    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text


async def test_banned_user_request_does_not_touch_user_row(client):
    """Comment 50 (M) — a banned user's request must NOT UPDATE the
    ``users`` row before 403'ing.

    Pre-fix the 403 gate lived after the ``last_login_at`` /
    ``last_ip`` / ``login_count`` debounce block, so every request
    from a banned user still committed an UPDATE — wasting WAL and
    making the admin "last seen" column lie about whether a blocked
    user was active. The fix moves the gate above the debounce
    block; this test pins the order down so a future refactor can't
    silently reintroduce the side effect.

    Setup: bootstrap a user, snapshot their (last_login_at,
    last_ip, login_count, username) values, then ban them while
    setting all four columns to recognisable poison values via the
    ORM. A request to ``/api/me`` must 403 and leave those columns
    exactly as we wrote them — no debounce-driven UPDATE.
    """
    from datetime import datetime, timedelta

    init = signed_init_data(5101, "ban_no_writes")
    await _bootstrap_user(client, 5101, "ban_no_writes")

    # Anchor poison values well outside the 5-min debounce so the
    # pre-fix code would unconditionally overwrite them.
    poison_login_at = datetime(2020, 1, 1) - timedelta(days=42)
    poison_ip = "10.255.255.254"
    poison_username = "ban_no_writes_poison"
    poison_count = 9999

    async with async_session() as session:
        user = (await session.execute(select(User).where(User.tg_user_id == 5101))).scalar_one()
        user.is_banned = True
        user.ban_reason = "ordering-regression"
        user.last_login_at = poison_login_at
        user.last_ip = poison_ip
        user.login_count = poison_count
        user.username = poison_username
        await session.commit()

    # The request must 403 with the banned-account detail and NOT
    # bump any of the debounced columns.
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 403, resp.text
    assert "заблокирован" in resp.json()["detail"]["message"]

    async with async_session() as session:
        user = (await session.execute(select(User).where(User.tg_user_id == 5101))).scalar_one()
        assert user.last_login_at == poison_login_at, (
            "banned request bumped last_login_at — Comment 50 regression"
        )
        assert user.last_ip == poison_ip, "banned request rewrote last_ip — Comment 50 regression"
        assert user.login_count == poison_count, (
            "banned request bumped login_count — Comment 50 regression"
        )
        # initData ships ``username='ban_no_writes'``; the pre-fix
        # path would have synced it back to that value on top of the
        # debounce bump.
        assert user.username == poison_username, (
            "banned request synced username from initData — Comment 50 regression"
        )


async def test_banned_user_403_includes_admin_username(client):
    """Item 24 — the 403 payload exposes the first admin's username so
    the frontend gate can deep-link "Связаться с админом" to
    ``https://t.me/<admin>``.
    """
    init = signed_init_data(5201, "ban_admin_target")
    await _bootstrap_user(client, 5201, "ban_admin_target")

    # Promote a second user to admin so the gate has somewhere to send
    # the appeal. The choice is deterministic (lowest-id admin with a
    # non-NULL username), so the only admin in the test environment
    # gets picked.
    init_admin = signed_init_data(5202, "appeal_admin")
    await _bootstrap_user(client, 5202, "appeal_admin")
    async with async_session() as session:
        admin_user = (
            await session.execute(select(User).where(User.tg_user_id == 5202))
        ).scalar_one()
        admin_user.is_admin = True
        await session.commit()
    # Reference ``init_admin`` so static analysis sees it as used —
    # the row was set up via /api/me bootstrap, not via this token.
    _ = init_admin

    await _set_user_flag(5201, banned=True)

    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["admin_username"] == "appeal_admin"


async def test_frozen_user_request_does_not_touch_user_row(client):
    """Companion to the banned-case: ``is_frozen`` must short-circuit
    the same way. The two flags lead to different 403 detail
    strings but the side-effect-suppression behaviour is identical.
    """
    from datetime import datetime, timedelta

    init = signed_init_data(5102, "freeze_no_writes")
    await _bootstrap_user(client, 5102, "freeze_no_writes")

    poison_login_at = datetime(2020, 1, 1) - timedelta(days=42)
    poison_ip = "10.255.255.253"
    poison_count = 7777

    async with async_session() as session:
        user = (await session.execute(select(User).where(User.tg_user_id == 5102))).scalar_one()
        user.is_frozen = True
        user.freeze_reason = "ordering-regression"
        user.last_login_at = poison_login_at
        user.last_ip = poison_ip
        user.login_count = poison_count
        await session.commit()

    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 403, resp.text
    assert "заморожен" in resp.json()["detail"]["message"]

    async with async_session() as session:
        user = (await session.execute(select(User).where(User.tg_user_id == 5102))).scalar_one()
        assert user.last_login_at == poison_login_at
        assert user.last_ip == poison_ip
        assert user.login_count == poison_count
