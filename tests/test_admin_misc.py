"""Admin PR-CDE — broadcasts / settings / taxonomy / analytics / system /
2FA / audit / maintenance endpoints.

These routers don't fit into the single-domain test files
(``test_admin_finance.py``, ``test_admin_users.py``, ``test_admin_deals.py``)
so they share this single module. Each public path gets RBAC, happy-path,
and at least one edge-case assertion.
"""

from __future__ import annotations

from sqlalchemy import select

from backend.app.auth_2fa import generate_secret, totp_now
from backend.app.db import async_session
from backend.app.models import (
    AdminAuditLog,
    AppSettings,
    Broadcast,
    Category,
    User,
)
from tests.helpers import auth_headers, signed_init_data


async def _bootstrap(client, *, tg_user_id: int, username: str) -> int:
    init = signed_init_data(tg_user_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _make_admin(client, tg: int = 1) -> tuple[str, int]:
    init = signed_init_data(tg, f"admin{tg}")
    uid = await _bootstrap(client, tg_user_id=tg, username=f"admin{tg}")
    async with async_session() as session:
        u = await session.get(User, uid)
        u.is_admin = True
        await session.commit()
    return init, uid


# ── Settings ────────────────────────────────────────────────────────────


async def test_settings_get_returns_defaults(client):
    admin_init, _ = await _make_admin(client, tg=1)
    resp = await client.get("/api/admin/settings", headers=auth_headers(admin_init))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "deal_commission_percent" in body
    assert "maintenance_enabled" in body
    assert "auto_withdraw_enabled" in body


async def test_settings_patch_persists_and_audits(client):
    admin_init, _ = await _make_admin(client, tg=1)
    resp = await client.patch(
        "/api/admin/settings",
        json={"deal_commission_percent": 7.5, "auto_withdraw_enabled": True},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deal_commission_percent"] == 7.5
    assert resp.json()["auto_withdraw_enabled"] is True

    async with async_session() as session:
        s = (
            await session.execute(select(AppSettings).order_by(AppSettings.id).limit(1))
        ).scalar_one()
        assert float(s.deal_commission_percent) == 7.5
        audits = (
            (
                await session.execute(
                    select(AdminAuditLog).where(AdminAuditLog.action == "settings.update")
                )
            )
            .scalars()
            .all()
        )
        assert len(audits) == 1


async def test_settings_patch_rbac(client):
    init = signed_init_data(10, "alice")
    await _bootstrap(client, tg_user_id=10, username="alice")
    resp = await client.patch(
        "/api/admin/settings",
        json={"deal_commission_percent": 99},
        headers=auth_headers(init),
    )
    assert resp.status_code == 403


# ── Maintenance public probe ────────────────────────────────────────────


async def test_public_maintenance_endpoint_open(client):
    resp = await client.get("/api/settings/maintenance")
    assert resp.status_code == 200
    body = resp.json()
    assert "enabled" in body
    assert "message" in body


async def test_maintenance_blocks_non_admin_writes(client):
    admin_init, _ = await _make_admin(client, tg=1)
    init = signed_init_data(10, "alice")
    await _bootstrap(client, tg_user_id=10, username="alice")

    # Turn maintenance on
    resp = await client.patch(
        "/api/admin/settings",
        json={"maintenance_enabled": True, "maintenance_message": "be back soon"},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 200

    # Non-admin write blocked
    blocked = await client.patch(
        "/api/me",
        json={"display_name": "alice prime"},
        headers=auth_headers(init),
    )
    assert blocked.status_code == 503

    # Admin write still goes through
    ok = await client.patch(
        "/api/admin/settings",
        json={"maintenance_enabled": False},
        headers=auth_headers(admin_init),
    )
    assert ok.status_code == 200


# ── Taxonomy ────────────────────────────────────────────────────────────


async def test_taxonomy_categories_crud(client):
    admin_init, _ = await _make_admin(client, tg=1)
    resp = await client.put(
        "/api/admin/categories",
        json={"slug": "new-cat", "name": "New", "icon": "✨"},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 200, resp.text
    cat_id = resp.json()["id"]

    listing = await client.get("/api/admin/categories", headers=auth_headers(admin_init))
    assert any(c["id"] == cat_id for c in listing.json())

    delete = await client.delete(
        f"/api/admin/categories/{cat_id}", headers=auth_headers(admin_init)
    )
    assert delete.status_code in (200, 204)

    async with async_session() as session:
        gone = (
            await session.execute(select(Category).where(Category.id == cat_id))
        ).scalar_one_or_none()
        assert gone is None


async def test_taxonomy_currencies_upsert(client):
    admin_init, _ = await _make_admin(client, tg=1)
    resp = await client.put(
        "/api/admin/currencies",
        json={
            "code": "JET",
            "name": "Jeton",
            "network": "TON",
            "decimals": 8,
            "min_deposit": 0.1,
            "min_withdraw": 0.2,
            "is_active": True,
        },
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == "JET"


async def test_taxonomy_rbac(client):
    init = signed_init_data(10, "alice")
    await _bootstrap(client, tg_user_id=10, username="alice")
    resp = await client.put(
        "/api/admin/categories",
        json={"slug": "x", "name": "x"},
        headers=auth_headers(init),
    )
    assert resp.status_code == 403


# ── Broadcasts ──────────────────────────────────────────────────────────


async def test_broadcasts_preview_and_send(client):
    admin_init, _ = await _make_admin(client, tg=1)
    await _bootstrap(client, tg_user_id=2, username="bob")
    await _bootstrap(client, tg_user_id=3, username="carol")

    preview = await client.post(
        "/api/admin/broadcasts/preview",
        json={"body": "Hello", "dispatch_inapp": True, "dispatch_dm": False},
        headers=auth_headers(admin_init),
    )
    assert preview.status_code == 200, preview.text
    count = preview.json()["total_recipients"]
    assert count >= 3

    send = await client.post(
        "/api/admin/broadcasts",
        json={"body": "Hello", "dispatch_inapp": True, "dispatch_dm": False},
        headers=auth_headers(admin_init),
    )
    assert send.status_code == 200, send.text
    assert send.json()["total_recipients"] == count

    async with async_session() as session:
        rows = (await session.execute(select(Broadcast))).scalars().all()
        assert len(rows) == 1


async def test_broadcasts_audience_filter_role(client):
    admin_init, _ = await _make_admin(client, tg=1)
    arbiter_id = await _bootstrap(client, tg_user_id=2, username="judge")
    await _bootstrap(client, tg_user_id=3, username="carol")
    async with async_session() as session:
        u = await session.get(User, arbiter_id)
        u.is_arbiter = True
        await session.commit()

    preview = await client.post(
        "/api/admin/broadcasts/preview",
        json={
            "body": "x",
            "audience_role": "arbiter",
            "dispatch_inapp": True,
            "dispatch_dm": False,
        },
        headers=auth_headers(admin_init),
    )
    assert preview.status_code == 200
    assert preview.json()["total_recipients"] == 1


async def test_broadcasts_rbac(client):
    init = signed_init_data(10, "alice")
    await _bootstrap(client, tg_user_id=10, username="alice")
    resp = await client.post(
        "/api/admin/broadcasts",
        json={"body": "x", "dispatch_inapp": True, "dispatch_dm": False},
        headers=auth_headers(init),
    )
    assert resp.status_code == 403


# ── Analytics ───────────────────────────────────────────────────────────


async def test_analytics_kpi_shape(client):
    admin_init, _ = await _make_admin(client, tg=1)
    resp = await client.get("/api/admin/analytics/kpi", headers=auth_headers(admin_init))
    assert resp.status_code == 200, resp.text
    for field in (
        "dau",
        "wau",
        "mau",
        "deals_24h",
        "open_arbitration",
        "pending_withdrawals",
    ):
        assert field in resp.json()


async def test_analytics_series_shape(client):
    admin_init, _ = await _make_admin(client, tg=1)
    resp = await client.get("/api/admin/analytics/series", headers=auth_headers(admin_init))
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["deals_count_30d"], list)
    assert isinstance(body["new_users_30d"], list)


async def test_analytics_rbac(client):
    init = signed_init_data(10, "alice")
    await _bootstrap(client, tg_user_id=10, username="alice")
    resp = await client.get("/api/admin/analytics/kpi", headers=auth_headers(init))
    assert resp.status_code == 403


# ── System ──────────────────────────────────────────────────────────────


async def test_system_status_returns_health(client):
    admin_init, _ = await _make_admin(client, tg=1)
    resp = await client.get("/api/admin/system/status", headers=auth_headers(admin_init))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["db_ok"] is True
    assert "cryptobot_configured" in body
    assert "bot_configured" in body


async def test_system_rbac(client):
    init = signed_init_data(10, "alice")
    await _bootstrap(client, tg_user_id=10, username="alice")
    resp = await client.get("/api/admin/system/status", headers=auth_headers(init))
    assert resp.status_code == 403


# ── 2FA ─────────────────────────────────────────────────────────────────


async def test_2fa_status_default_off(client):
    admin_init, _ = await _make_admin(client, tg=1)
    resp = await client.get("/api/admin/2fa/status", headers=auth_headers(admin_init))
    assert resp.status_code == 200, resp.text
    assert resp.json()["enabled"] is False


async def test_2fa_setup_and_enable_flow(client):
    admin_init, admin_id = await _make_admin(client, tg=1)
    setup = await client.post("/api/admin/2fa/setup", headers=auth_headers(admin_init))
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    code = totp_now(secret)
    enable = await client.post(
        "/api/admin/2fa/enable",
        json={"secret": secret, "code": code},
        headers=auth_headers(admin_init),
    )
    assert enable.status_code == 200, enable.text
    async with async_session() as session:
        u = await session.get(User, admin_id)
        assert u.totp_enabled is True
        assert u.totp_secret == secret


async def test_2fa_enable_rejects_wrong_code(client):
    admin_init, _ = await _make_admin(client, tg=1)
    secret = generate_secret()
    resp = await client.post(
        "/api/admin/2fa/enable",
        json={"secret": secret, "code": "000000"},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code in (400, 401)


async def test_2fa_rotation_requires_current_code(client):
    """Once 2FA is on, swapping the secret must require the current code.

    Without this guard a stolen admin session could silently replace
    the secret with one the attacker controls.
    """
    admin_init, admin_id = await _make_admin(client, tg=1)
    # Initial enrolment — no current_code required.
    setup = await client.post("/api/admin/2fa/setup", headers=auth_headers(admin_init))
    secret_a = setup.json()["secret"]
    enable = await client.post(
        "/api/admin/2fa/enable",
        json={"secret": secret_a, "code": totp_now(secret_a)},
        headers=auth_headers(admin_init),
    )
    assert enable.status_code == 200, enable.text

    # Attempt rotation WITHOUT current_code — must fail 401.
    secret_b = generate_secret()
    resp = await client.post(
        "/api/admin/2fa/enable",
        json={"secret": secret_b, "code": totp_now(secret_b)},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 401, resp.text
    async with async_session() as session:
        u = await session.get(User, admin_id)
        assert u.totp_secret == secret_a  # unchanged

    # Rotation WITH the wrong current_code — must still fail.
    resp = await client.post(
        "/api/admin/2fa/enable",
        json={"secret": secret_b, "code": totp_now(secret_b), "current_code": "000000"},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 401

    # Rotation WITH a valid current_code — must succeed and persist
    # the new secret. Reset the replay counter so the test isn't bound
    # to wall-clock 30-second windows; in production the admin would
    # simply wait for the next code before rotating.
    async with async_session() as session:
        u = await session.get(User, admin_id)
        u.totp_last_counter = -1
        await session.commit()
    resp = await client.post(
        "/api/admin/2fa/enable",
        json={
            "secret": secret_b,
            "code": totp_now(secret_b),
            "current_code": totp_now(secret_a),
        },
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 200, resp.text
    async with async_session() as session:
        u = await session.get(User, admin_id)
        assert u.totp_secret == secret_b


async def test_2fa_replay_protection(client):
    """The same TOTP code cannot be used twice within its 30s window."""
    admin_init, _ = await _make_admin(client, tg=1)
    setup = await client.post("/api/admin/2fa/setup", headers=auth_headers(admin_init))
    secret = setup.json()["secret"]
    code = totp_now(secret)
    enable = await client.post(
        "/api/admin/2fa/enable",
        json={"secret": secret, "code": code},
        headers=auth_headers(admin_init),
    )
    assert enable.status_code == 200

    # Try to disable using the same code that just enabled — replay
    # must be rejected.
    resp = await client.post(
        "/api/admin/2fa/disable",
        json={"code": code},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 401, resp.text


# ── System: redis flush 2FA guard ───────────────────────────────────────


async def test_redis_flush_requires_2fa(client):
    """``POST /api/admin/system/redis/flush`` is gated by ``require_totp``.

    Without 2FA configured the dependency raises 403; with 2FA on it
    raises 401 when the header is missing or invalid.
    """
    admin_init, admin_id = await _make_admin(client, tg=1)
    # 2FA not configured yet → 403.
    resp = await client.post(
        "/api/admin/system/redis/flush",
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 403, resp.text

    # Enable 2FA, then try without header → 401.
    setup = await client.post("/api/admin/2fa/setup", headers=auth_headers(admin_init))
    secret = setup.json()["secret"]
    await client.post(
        "/api/admin/2fa/enable",
        json={"secret": secret, "code": totp_now(secret)},
        headers=auth_headers(admin_init),
    )
    resp = await client.post(
        "/api/admin/system/redis/flush",
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 401, resp.text

    # Reset the replay counter so the test isn't bound to wall-clock
    # 30-second windows. In production the user would simply wait for
    # the next 30s window and submit a fresh code.
    async with async_session() as session:
        u = await session.get(User, admin_id)
        u.totp_last_counter = -1
        await session.commit()
    headers = {**auth_headers(admin_init), "X-Totp-Code": totp_now(secret)}
    resp = await client.post("/api/admin/system/redis/flush", headers=headers)
    assert resp.status_code == 200, resp.text
    # Action is audit-logged.
    async with async_session() as session:
        audits = (
            (
                await session.execute(
                    select(AdminAuditLog).where(AdminAuditLog.action == "system.redis_flush")
                )
            )
            .scalars()
            .all()
        )
        assert len(audits) == 1
        assert audits[0].actor_id == admin_id


# ── Audit ───────────────────────────────────────────────────────────────


async def test_audit_log_lists_actions(client):
    admin_init, _ = await _make_admin(client, tg=1)
    # Touch settings to write an audit row
    await client.patch(
        "/api/admin/settings",
        json={"deal_commission_percent": 4.0},
        headers=auth_headers(admin_init),
    )
    resp = await client.get(
        "/api/admin/audit?action=settings.update", headers=auth_headers(admin_init)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["action"] == "settings.update"


async def test_audit_log_rbac(client):
    init = signed_init_data(10, "alice")
    await _bootstrap(client, tg_user_id=10, username="alice")
    resp = await client.get("/api/admin/audit", headers=auth_headers(init))
    assert resp.status_code == 403
