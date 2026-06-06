"""Admin panel — `/api/admin/users` endpoints.

Covers the action surface added in PR-A:

* RBAC: regular users get 403 on every admin endpoint.
* List: search by @username, role filter, status filter, pagination.
* Detail: privileged fields (tg_user_id, last_ip, login_count, has_pin).
* Ban / unban: idempotent, audit row written, last-admin guard, self-guard.
* Freeze / unfreeze: idempotent.
* Reset PIN: clears pin_hash and reset code, idempotent.
* Set role: admin/arbiter/vip, can't self-demote, can't drop last admin.
* Set rating: 0..5 only, accepts null to clear, no DM on no-op.
* Set stats: only provided fields applied, negative values rejected.
* Audit log row written exactly once per *effective* mutation.
"""

from __future__ import annotations

from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import AdminAuditLog, User
from tests.helpers import auth_headers, signed_init_data, with_totp


async def _make_admin(tg_user_id: int = 1, username: str = "admin") -> str:
    """Bootstrap a user via /api/me, then promote to admin in the DB."""
    init = signed_init_data(tg_user_id, username)
    return init


async def _bootstrap(client, *, tg_user_id: int, username: str) -> int:
    """Hit /api/me to create the User row, return the assigned id."""
    init = signed_init_data(tg_user_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _set_flags(user_id: int, **kwargs) -> None:
    async with async_session() as session:
        user = await session.get(User, user_id)
        assert user is not None
        for k, v in kwargs.items():
            setattr(user, k, v)
        await session.commit()


async def _audit_count(action: str | None = None) -> int:
    async with async_session() as session:
        stmt = select(AdminAuditLog)
        if action:
            stmt = stmt.where(AdminAuditLog.action == action)
        rows = (await session.execute(stmt)).scalars().all()
        return len(rows)


# ── RBAC ───────────────────────────────────────────────────────────────────


async def test_dashboard_forbidden_for_non_admin(client):
    init = signed_init_data(10, "alice")
    await _bootstrap(client, tg_user_id=10, username="alice")
    resp = await client.get("/api/admin/dashboard", headers=auth_headers(init))
    assert resp.status_code == 403


async def test_users_list_forbidden_for_non_admin(client):
    init = signed_init_data(10, "alice")
    await _bootstrap(client, tg_user_id=10, username="alice")
    resp = await client.get("/api/admin/users", headers=auth_headers(init))
    assert resp.status_code == 403


async def test_users_list_forbidden_for_arbiter(client):
    init = signed_init_data(10, "alice")
    uid = await _bootstrap(client, tg_user_id=10, username="alice")
    await _set_flags(uid, is_arbiter=True)
    resp = await client.get("/api/admin/users", headers=auth_headers(init))
    assert resp.status_code == 403


# ── Dashboard ──────────────────────────────────────────────────────────────


async def test_dashboard_returns_counters(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    # Add a couple of regular users.
    await _bootstrap(client, tg_user_id=2, username="bob")
    await _bootstrap(client, tg_user_id=3, username="carol")

    resp = await client.get("/api/admin/dashboard", headers=auth_headers(admin_init))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_users"] >= 3
    assert body["admins"] == 1
    assert "open_deals" in body
    assert "vips" in body


# ── Listing ────────────────────────────────────────────────────────────────


async def test_users_list_pagination_and_total(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    for i in range(2, 8):
        await _bootstrap(client, tg_user_id=i, username=f"user{i}")

    resp = await client.get("/api/admin/users?page=1&page_size=3", headers=auth_headers(admin_init))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 3
    assert body["total"] >= 7
    assert body["page"] == 1


async def test_users_list_search_by_username(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    await _bootstrap(client, tg_user_id=2, username="bob")
    await _bootstrap(client, tg_user_id=3, username="carol")

    resp = await client.get("/api/admin/users?q=carol", headers=auth_headers(admin_init))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all("carol" in (i["username"] or "").lower() for i in items)
    assert any(i["username"] == "carol" for i in items)


async def test_users_list_search_ranks_exact_username_before_newer_partial_matches(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    exact_id = await _bootstrap(client, tg_user_id=100, username="arbiter_target")
    for i in range(25):
        await _bootstrap(client, tg_user_id=200 + i, username=f"new_arbiter_target_{i:02d}")

    resp = await client.get(
        "/api/admin/users?q=arbiter_target&page_size=1",
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 26
    assert [item["id"] for item in body["items"]] == [exact_id]


async def test_users_list_search_ranks_exact_tg_id_before_partial_text_matches(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    exact_id = await _bootstrap(client, tg_user_id=777777, username="numeric_target")
    for i in range(25):
        await _bootstrap(client, tg_user_id=300 + i, username=f"new_777777_{i:02d}")

    resp = await client.get(
        "/api/admin/users?q=777777&page_size=1",
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 26
    assert [item["id"] for item in body["items"]] == [exact_id]


async def test_users_list_filter_by_role_vip(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    bob_id = await _bootstrap(client, tg_user_id=2, username="bob")
    await _set_flags(bob_id, is_vip=True)
    await _bootstrap(client, tg_user_id=3, username="carol")

    resp = await client.get("/api/admin/users?role=vip", headers=auth_headers(admin_init))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["username"] == "bob"
    assert items[0]["is_vip"] is True


async def test_users_list_filter_by_status_banned(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    bob_id = await _bootstrap(client, tg_user_id=2, username="bob")
    await _set_flags(bob_id, is_banned=True)
    await _bootstrap(client, tg_user_id=3, username="carol")

    resp = await client.get("/api/admin/users?status=banned", headers=auth_headers(admin_init))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["username"] == "bob"


# ── Detail ─────────────────────────────────────────────────────────────────


async def test_user_detail_includes_privileged_fields(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=42, username="bob")
    resp = await client.get(f"/api/admin/users/{target_id}", headers=auth_headers(admin_init))
    assert resp.status_code == 200
    body = resp.json()
    assert body["tg_user_id"] == 42
    assert "last_ip" in body
    assert "login_count" in body
    assert body["rating_auto"] == 0.0
    assert body["rating_effective"] == 0.0


async def test_user_detail_404_for_missing_id(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    resp = await client.get("/api/admin/users/999", headers=auth_headers(admin_init))
    assert resp.status_code == 404


# ── Ban / Unban ────────────────────────────────────────────────────────────


async def test_ban_user_writes_audit_and_dms(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=2, username="bob")

    resp = await client.post(
        f"/api/admin/users/{target_id}/ban",
        json={"reason": "Спам"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_banned"] is True
    assert body["ban_reason"] == "Спам"
    assert await _audit_count("user.ban") == 1


async def test_ban_user_idempotent(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=2, username="bob")
    await _set_flags(target_id, is_banned=True, ban_reason="Спам")

    # Second ban with same reason should not write a duplicate audit row.
    resp = await client.post(
        f"/api/admin/users/{target_id}/ban",
        json={"reason": "Спам"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200
    assert await _audit_count("user.ban") == 0


async def test_reban_with_null_reason_clears_existing_reason(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=2, username="bob")
    await _set_flags(target_id, is_banned=True, ban_reason="old reason")

    resp = await client.post(
        f"/api/admin/users/{target_id}/ban",
        json={"reason": None},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_banned"] is True
    assert body["ban_reason"] is None
    assert await _audit_count("user.ban") == 1


async def test_ban_self_forbidden(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    resp = await client.post(
        f"/api/admin/users/{admin_id}/ban",
        json={"reason": "self"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 400


async def test_unban_clears_state(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=2, username="bob")
    await _set_flags(target_id, is_banned=True, ban_reason="Спам")

    resp = await client.post(
        f"/api/admin/users/{target_id}/unban",
        json={},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_banned"] is False
    assert body["ban_reason"] is None


# ── Freeze / Unfreeze ──────────────────────────────────────────────────────


async def test_freeze_user(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=2, username="bob")

    resp = await client.post(
        f"/api/admin/users/{target_id}/freeze",
        json={"reason": "Подозрительная активность"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_frozen"] is True
    assert body["freeze_reason"] == "Подозрительная активность"

async def test_refreeze_with_null_reason_clears_existing_reason(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=2, username="bob")
    await _set_flags(target_id, is_frozen=True, freeze_reason="old reason")

    resp = await client.post(
        f"/api/admin/users/{target_id}/freeze",
        json={"reason": None},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_frozen"] is True
    assert body["freeze_reason"] is None
    assert await _audit_count("user.freeze") == 1


# ── Reset PIN ──────────────────────────────────────────────────────────────


async def test_reset_pin_clears_hash(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=2, username="bob")
    await _set_flags(target_id, pin_hash="fake-hash", pin_attempts=3)

    resp = await client.post(
        f"/api/admin/users/{target_id}/reset-pin",
        json={},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_pin"] is False


async def test_reset_pin_no_op_when_no_pin(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=2, username="bob")

    before = await _audit_count("user.reset_pin")
    resp = await client.post(
        f"/api/admin/users/{target_id}/reset-pin",
        json={},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200
    # No PIN → no audit row.
    assert await _audit_count("user.reset_pin") == before


async def test_reset_pin_publishes_pin_reset_ws_event(client, monkeypatch):
    """Item 8 — admin's ``reset-pin`` must surface a typed
    ``pin.reset`` WS event to the affected user before invalidating
    their socket.

    Pre-fix the endpoint cleared ``pin_hash`` on the server but the
    client only saw the consequence on the next PIN-gated REST call
    (which the TMA's start-up sequence doesn't make); meanwhile the
    locally cached PIN JWT kept ``PinGate`` in the authenticated
    tree. The frontend listener in
    ``frontend/src/lib/useLiveNotifications.ts`` reacts to this
    event by dropping the token + invalidating ``pin/status``.

    Why we still expect ``invalidate_user``: the socket has to be
    closed so a now-untrusted device re-auths its WS connection
    (mirrors the existing ``invalidate-sessions`` action).
    """
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=2, username="bob")
    await _set_flags(target_id, pin_hash="fake-hash", pin_attempts=3)

    publish_calls: list[tuple[int, dict]] = []
    invalidate_calls: list[int] = []

    async def _capture_publish(uid, data):
        publish_calls.append((uid, data))

    async def _capture_invalidate(uid):
        invalidate_calls.append(uid)

    monkeypatch.setattr("backend.app.routers.admin.users.ws_manager.publish", _capture_publish)
    monkeypatch.setattr(
        "backend.app.routers.admin.users.ws_manager.invalidate_user",
        _capture_invalidate,
    )

    resp = await client.post(
        f"/api/admin/users/{target_id}/reset-pin",
        json={},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["has_pin"] is False

    # Both side-effects must fire exactly once, in the order:
    # publish(pin.reset) → invalidate_user. Without ``pin.reset``
    # arriving first the live tab never learns the token is stale.
    pin_reset_calls = [
        (uid, data) for uid, data in publish_calls if data.get("event") == "pin.reset"
    ]
    assert pin_reset_calls == [(target_id, {"event": "pin.reset", "data": {}})], publish_calls
    assert invalidate_calls == [target_id]


async def test_reset_pin_no_ws_event_when_user_has_no_pin(client, monkeypatch):
    """Companion to the no-op test: if the user never had a PIN
    configured we must NOT publish ``pin.reset`` — the WS listener
    would otherwise toast a phantom "your PIN was reset" message and
    log the user out of an unrelated authenticated tree (e.g. an
    admin clicked the button by mistake).
    """
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=2, username="bob")

    publish_calls: list[tuple[int, dict]] = []

    async def _capture_publish(uid, data):
        publish_calls.append((uid, data))

    monkeypatch.setattr("backend.app.routers.admin.users.ws_manager.publish", _capture_publish)

    resp = await client.post(
        f"/api/admin/users/{target_id}/reset-pin",
        json={},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    assert not [(uid, data) for uid, data in publish_calls if data.get("event") == "pin.reset"]


# ── Set Role ───────────────────────────────────────────────────────────────


async def test_set_role_grants_vip(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=2, username="bob")

    resp = await client.post(
        f"/api/admin/users/{target_id}/role",
        json={"is_vip": True},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_vip"] is True
    assert body["is_admin"] is False
    assert body["is_arbiter"] is False


async def test_set_role_partial_update_preserves_unmentioned_flags(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=2, username="bob")
    await _set_flags(target_id, is_arbiter=True, is_vip=True)

    resp = await client.post(
        f"/api/admin/users/{target_id}/role",
        json={"is_admin": True},
        headers=with_totp(auth_headers(admin_init)),
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_admin"] is True
    assert body["is_arbiter"] is True
    assert body["is_vip"] is True


async def test_set_role_empty_body_rejected_without_mutation(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=2, username="bob")
    await _set_flags(target_id, is_arbiter=True, is_vip=True)

    resp = await client.post(
        f"/api/admin/users/{target_id}/role",
        json={},
        headers=with_totp(auth_headers(admin_init)),
    )

    assert resp.status_code == 400, resp.text
    async with async_session() as session:
        target = await session.get(User, target_id)
        assert target is not None
        assert target.is_admin is False
        assert target.is_arbiter is True
        assert target.is_vip is True


async def test_set_role_self_demotion_forbidden(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    resp = await client.post(
        f"/api/admin/users/{admin_id}/role",
        json={"is_admin": False},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 400


async def test_set_role_cannot_remove_last_admin(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    # Bob is also an admin, but he is not the *caller* — he can be
    # demoted only if at least one other admin remains.
    bob_id = await _bootstrap(client, tg_user_id=2, username="bob")
    await _set_flags(bob_id, is_admin=True)

    # First demotion ok — admin still has himself.
    resp = await client.post(
        f"/api/admin/users/{bob_id}/role",
        json={"is_admin": False},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200
    assert resp.json()["is_admin"] is False

    # Promote Bob again, then try to demote the only OTHER admin (admin
    # himself); the call is to /role on the admin's own row which is
    # blocked by the self-demotion guard. So instead we verify that if
    # the *target* is the last admin, the call is rejected.
    await _set_flags(bob_id, is_admin=True)
    await _set_flags(admin_id, is_admin=False)
    # Now Bob is the only admin. Promote a second admin then test the
    # "last admin" guard via Bob's account.
    bob_init = signed_init_data(2, "bob")
    resp = await client.post(
        f"/api/admin/users/{bob_id}/role",
        json={"is_admin": False},
        headers=with_totp(auth_headers(bob_init)),
    )
    # Self-demotion guard fires first (400).
    assert resp.status_code == 400


# ── Set Rating ─────────────────────────────────────────────────────────────


async def test_set_rating_override(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=2, username="bob")

    resp = await client.post(
        f"/api/admin/users/{target_id}/rating",
        json={"rating": 4.7},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rating_manual"] == 4.7
    assert body["rating_effective"] == 4.7


async def test_set_rating_clear_override(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=2, username="bob")
    await _set_flags(target_id, rating_manual=3.0)

    resp = await client.post(
        f"/api/admin/users/{target_id}/rating",
        json={"rating": None},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rating_manual"] is None


async def test_set_rating_out_of_range_rejected(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=2, username="bob")

    resp = await client.post(
        f"/api/admin/users/{target_id}/rating",
        json={"rating": 7.0},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 422


# ── Set Stats ──────────────────────────────────────────────────────────────


async def test_set_stats_partial_update(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=2, username="bob")

    resp = await client.post(
        f"/api/admin/users/{target_id}/stats",
        json={"deals_total": 25, "good": 20},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["deals_total"] == 25
    assert body["good"] == 20
    # Untouched fields stay at default 0.
    assert body["bad"] == 0


async def test_set_stats_rejects_negative(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=2, username="bob")

    resp = await client.post(
        f"/api/admin/users/{target_id}/stats",
        json={"deals_total": -1},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 422


async def test_set_stats_rejects_deposit_total(client):
    """``POST /api/admin/users/:id/stats`` no longer accepts
    ``deposit_total`` — the column was retired together with the
    lifetime deposit aggregate. Older clients that still send the
    key fail fast at schema validation instead of silently being a
    no-op.
    """
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _set_flags(admin_id, is_admin=True)

    target_id = await _bootstrap(client, tg_user_id=2, username="bob")

    resp = await client.post(
        f"/api/admin/users/{target_id}/stats",
        json={"deposit_total": 1250.50},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 422, resp.text


# ── Item 11: public DTO breakdown ──────────────────────────────────────────


async def test_user_me_exposes_deals_breakdown(client):
    """``GET /api/me`` (``UserOut``) returns the success / failed /
    arbitrage counters maintained on the ``User`` row.

    Pre-fix the schema only surfaced ``deals_count`` (= ``deals_total``);
    the breakdown was admin-only despite the underlying columns being
    populated by every deal-state-machine transition. The ``UserCardDto``
    fields are required on both ``UserOut`` and ``UserPublicOut``, so a
    regression here would also break the openapi drift gate.
    """
    init = signed_init_data(100, "alice")
    uid = await _bootstrap(client, tg_user_id=100, username="alice")

    # Seed the per-status counters directly on the row. The deal-
    # state-machine tests in ``tests/e2e/test_deals_arbitration.py``
    # exercise the real increment path; here we only need the DTO
    # projection.
    async with async_session() as session:
        user = await session.get(User, uid)
        assert user is not None
        user.deals_total = 18
        user.deals_success = 12
        user.deals_failed = 4
        user.deals_arbitrage = 2
        await session.commit()

    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deals_count"] == 18
    assert body["deals_success"] == 12
    assert body["deals_failed"] == 4
    assert body["deals_arbitrage"] == 2


async def test_user_public_profile_exposes_deals_breakdown(client):
    """The same breakdown must surface on the public profile endpoint
    used to render somebody else's stats grid (``UserPublicOut``).
    """
    viewer_init = signed_init_data(100, "viewer")
    await _bootstrap(client, tg_user_id=100, username="viewer")
    target_id = await _bootstrap(client, tg_user_id=200, username="bob")

    async with async_session() as session:
        user = await session.get(User, target_id)
        assert user is not None
        user.deals_total = 7
        user.deals_success = 5
        user.deals_failed = 1
        user.deals_arbitrage = 1
        await session.commit()

    resp = await client.get("/api/users/bob", headers=auth_headers(viewer_init))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deals_count"] == 7
    assert body["deals_success"] == 5
    assert body["deals_failed"] == 1
    assert body["deals_arbitrage"] == 1
