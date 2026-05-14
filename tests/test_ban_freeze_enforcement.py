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
    assert "заблокирован" in resp.json().get("detail", "")


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
    assert "заморожен" in resp.json().get("detail", "")


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
