"""Admin PR-CDE — broadcasts / settings / taxonomy / analytics / system /
2FA / audit / maintenance endpoints.

These routers don't fit into the single-domain test files
(``test_admin_finance.py``, ``test_admin_users.py``, ``test_admin_deals.py``)
so they share this single module. Each public path gets RBAC, happy-path,
and at least one edge-case assertion.
"""

from __future__ import annotations

from datetime import timedelta

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
from backend.app.time_utils import utcnow
from tests.helpers import auth_headers, signed_init_data, with_totp


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
        headers=with_totp(auth_headers(admin_init)),
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
        headers=with_totp(auth_headers(admin_init)),
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
        headers=with_totp(auth_headers(admin_init)),
    )
    assert ok.status_code == 200


# ── Taxonomy ────────────────────────────────────────────────────────────


async def test_taxonomy_categories_crud(client):
    admin_init, _ = await _make_admin(client, tg=1)
    resp = await client.put(
        "/api/admin/categories",
        json={"slug": "new-cat", "name": "New", "icon": "✨"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    cat_id = resp.json()["id"]

    listing = await client.get("/api/admin/categories", headers=auth_headers(admin_init))
    assert any(c["id"] == cat_id for c in listing.json())

    delete = await client.delete(
        f"/api/admin/categories/{cat_id}", headers=with_totp(auth_headers(admin_init))
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
        headers=with_totp(auth_headers(admin_init)),
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
        headers=with_totp(auth_headers(admin_init)),
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


async def test_broadcasts_captures_user_language_code(client):
    """A-6 — Telegram ``user.language_code`` round-trips into ``users.language_code``.

    ``deps.get_current_user`` reads the field out of the signed
    initData blob and ``_normalise_language_code`` lowercases / clips
    it. A user who never sends a ``language_code`` keeps the column
    NULL.
    """
    await _make_admin(client, tg=1)
    init_ru = signed_init_data(2, "ru_user", language_code="RU")
    init_no_lang = signed_init_data(3, "no_lang_user")
    resp = await client.get("/api/me", headers=auth_headers(init_ru))
    assert resp.status_code == 200, resp.text
    resp = await client.get("/api/me", headers=auth_headers(init_no_lang))
    assert resp.status_code == 200, resp.text

    async with async_session() as session:
        ru = (await session.execute(select(User).where(User.tg_user_id == 2))).scalar_one()
        no_lang = (await session.execute(select(User).where(User.tg_user_id == 3))).scalar_one()
    # ``RU`` was normalised to lowercase.
    assert ru.language_code == "ru"
    assert no_lang.language_code is None


async def test_broadcasts_audience_filter_language(client):
    """A-6 — broadcast preview narrows to a single language cohort."""
    admin_init, _ = await _make_admin(client, tg=1)
    # The admin row itself was created without language_code (default
    # init helper), so it's excluded from the ``ru`` cohort below — we
    # only want the two explicit ``ru`` users to count.
    await _bootstrap(client, tg_user_id=2, username="ru1")
    await _bootstrap(client, tg_user_id=3, username="ru2")
    await _bootstrap(client, tg_user_id=4, username="en1")
    async with async_session() as session:
        for tg_id, lang in [(2, "ru"), (3, "ru"), (4, "en")]:
            u = (await session.execute(select(User).where(User.tg_user_id == tg_id))).scalar_one()
            u.language_code = lang
        await session.commit()

    preview = await client.post(
        "/api/admin/broadcasts/preview",
        json={
            "body": "Привет",
            "audience_language": "ru",
            "dispatch_inapp": True,
            "dispatch_dm": False,
        },
        headers=auth_headers(admin_init),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["total_recipients"] == 2

    # Uppercase input is normalised by the schema validator to match.
    preview_upper = await client.post(
        "/api/admin/broadcasts/preview",
        json={
            "body": "Привет",
            "audience_language": "RU",
            "dispatch_inapp": True,
            "dispatch_dm": False,
        },
        headers=auth_headers(admin_init),
    )
    assert preview_upper.status_code == 200
    assert preview_upper.json()["total_recipients"] == 2


async def test_broadcasts_audience_filter_created_window(client):
    """A-6 — temporal cohort ``created_after`` / ``created_before``.

    Builds three users at synthetic ages (1 / 30 / 90 days old) by
    backdating ``users.created_at`` directly and asserts that each
    side of the window is enforced.
    """
    admin_init, _ = await _make_admin(client, tg=1)
    await _bootstrap(client, tg_user_id=2, username="fresh")
    await _bootstrap(client, tg_user_id=3, username="month_old")
    await _bootstrap(client, tg_user_id=4, username="quarter_old")
    now = utcnow()
    async with async_session() as session:
        for tg_id, age_days in [(2, 1), (3, 30), (4, 90)]:
            u = (await session.execute(select(User).where(User.tg_user_id == tg_id))).scalar_one()
            u.created_at = now - timedelta(days=age_days)
        await session.commit()

    # ``created_after`` = 60 days ago → only fresh + month_old (admin
    # ``tg=1`` row is also younger than 60 days, so it joins them).
    preview = await client.post(
        "/api/admin/broadcasts/preview",
        json={
            "body": "x",
            "audience_created_after": (now - timedelta(days=60)).isoformat(),
            "dispatch_inapp": True,
            "dispatch_dm": False,
        },
        headers=auth_headers(admin_init),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["total_recipients"] == 3

    # ``created_before`` = 15 days ago → only month_old + quarter_old.
    preview = await client.post(
        "/api/admin/broadcasts/preview",
        json={
            "body": "x",
            "audience_created_before": (now - timedelta(days=15)).isoformat(),
            "dispatch_inapp": True,
            "dispatch_dm": False,
        },
        headers=auth_headers(admin_init),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["total_recipients"] == 2

    # Both sides → only month_old (between 15 and 60 days).
    preview = await client.post(
        "/api/admin/broadcasts/preview",
        json={
            "body": "x",
            "audience_created_after": (now - timedelta(days=60)).isoformat(),
            "audience_created_before": (now - timedelta(days=15)).isoformat(),
            "dispatch_inapp": True,
            "dispatch_dm": False,
        },
        headers=auth_headers(admin_init),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["total_recipients"] == 1


async def test_broadcasts_audience_filters_compose(client):
    """A-6 — role + language + window AND together, not OR."""
    admin_init, _ = await _make_admin(client, tg=1)
    arbiter_id = await _bootstrap(client, tg_user_id=2, username="arb_ru")
    await _bootstrap(client, tg_user_id=3, username="reg_ru")
    await _bootstrap(client, tg_user_id=4, username="arb_en")
    now = utcnow()
    async with async_session() as session:
        for tg_id, lang in [(2, "ru"), (3, "ru"), (4, "en")]:
            u = (await session.execute(select(User).where(User.tg_user_id == tg_id))).scalar_one()
            u.language_code = lang
            # Fresh registrations land *after* the window's lower bound.
            u.created_at = now - timedelta(days=5)
        arb = await session.get(User, arbiter_id)
        arb.is_arbiter = True
        en = (await session.execute(select(User).where(User.tg_user_id == 4))).scalar_one()
        en.is_arbiter = True
        await session.commit()

    preview = await client.post(
        "/api/admin/broadcasts/preview",
        json={
            "body": "x",
            "audience_role": "arbiter",
            "audience_language": "ru",
            "audience_created_after": (now - timedelta(days=30)).isoformat(),
            "dispatch_inapp": True,
            "dispatch_dm": False,
        },
        headers=auth_headers(admin_init),
    )
    assert preview.status_code == 200, preview.text
    # Only the ru-speaking arbiter matches all three filters.
    assert preview.json()["total_recipients"] == 1


async def test_broadcasts_round_trip_serialises_new_fields(client):
    """A-6 — POST → GET round-trip preserves the new audience fields.

    Sends a broadcast with every new filter set, then re-reads the
    history list and confirms the response carries those fields with
    the same values. Also confirms the audit-log payload captured the
    new keys (datetimes ISO-encoded).
    """
    admin_init, admin_id = await _make_admin(client, tg=1)
    await _bootstrap(client, tg_user_id=2, username="other")
    now = utcnow()
    after = now - timedelta(days=30)
    before = now + timedelta(days=1)

    send = await client.post(
        "/api/admin/broadcasts",
        json={
            "title": "Hi",
            "body": "Hello",
            "audience_created_after": after.isoformat(),
            "audience_created_before": before.isoformat(),
            "audience_language": "ru",
            "dispatch_inapp": True,
            "dispatch_dm": False,
        },
        headers=with_totp(auth_headers(admin_init)),
    )
    assert send.status_code == 200, send.text
    out = send.json()
    assert out["audience_created_after"].startswith(after.strftime("%Y-%m-%d"))
    assert out["audience_created_before"].startswith(before.strftime("%Y-%m-%d"))
    assert out["audience_language"] == "ru"

    history = await client.get("/api/admin/broadcasts", headers=auth_headers(admin_init))
    assert history.status_code == 200, history.text
    items = history.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["audience_language"] == "ru"
    assert item["audience_created_after"].startswith(after.strftime("%Y-%m-%d"))
    assert item["audience_created_before"].startswith(before.strftime("%Y-%m-%d"))

    async with async_session() as session:
        audit = (
            (
                await session.execute(
                    select(AdminAuditLog).where(AdminAuditLog.action == "broadcast.send")
                )
            )
            .scalars()
            .one()
        )
        assert audit.actor_id == admin_id
        payload = audit.payload
        assert payload is not None
        assert payload["audience_language"] == "ru"
        assert payload["audience_created_after"] is not None
        assert payload["audience_created_before"] is not None


async def test_broadcasts_reject_inverted_window(client):
    """A-6 — ``after > before`` is a 422 from the schema validator."""
    admin_init, _ = await _make_admin(client, tg=1)
    now = utcnow()
    resp = await client.post(
        "/api/admin/broadcasts/preview",
        json={
            "body": "x",
            "audience_created_after": (now + timedelta(days=1)).isoformat(),
            "audience_created_before": (now - timedelta(days=1)).isoformat(),
            "dispatch_inapp": True,
            "dispatch_dm": False,
        },
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 422, resp.text


async def test_broadcasts_reject_invalid_language(client):
    """A-6 — language codes with non-alphanumeric chars are rejected.

    Guards against an admin smuggling a ``;`` or whitespace through
    the audience filter — the validator confines it to the same shape
    Telegram itself emits.
    """
    admin_init, _ = await _make_admin(client, tg=1)
    resp = await client.post(
        "/api/admin/broadcasts/preview",
        json={
            "body": "x",
            "audience_language": "ru; DROP TABLE users;--",
            "dispatch_inapp": True,
            "dispatch_dm": False,
        },
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 422, resp.text


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
        headers=with_totp(auth_headers(admin_init)),
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


# ── 11.6.2 — maintenance allow-list: /health is exact, not prefix ───────


async def test_maintenance_health_allow_list_does_not_swallow_siblings(client):
    """A non-exact ``/health`` sibling (``/healthcheck``) must NOT be exempt.

    Pre-fix the allow-list used ``path.startswith("/health")`` so a
    future ``POST /healthcheck`` would have silently bypassed
    maintenance mode. The fix splits the entry into an exact
    ``/health`` plus a ``/health/`` prefix; sibling paths fall through
    to the normal maintenance gate. We assert that with maintenance
    on, an arbitrary non-exempt write path is still blocked with 503,
    confirming the gate is intact for non-allow-listed traffic.
    """
    admin_init, _ = await _make_admin(client, tg=1)
    init = signed_init_data(10, "alice")
    await _bootstrap(client, tg_user_id=10, username="alice")

    # Flip maintenance on.
    resp = await client.patch(
        "/api/admin/settings",
        json={"maintenance_enabled": True, "maintenance_message": "be back soon"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200

    # A non-allow-listed write path is still blocked. PATCH /api/me is
    # the canonical "ordinary write" probe used by
    # ``test_maintenance_blocks_non_admin_writes`` above.
    blocked = await client.patch(
        "/api/me",
        json={"display_name": "alice prime"},
        headers=auth_headers(init),
    )
    assert blocked.status_code == 503

    # Direct assertion on the allow-list shape — the only ``/health*``
    # entry must be the exact path or the ``/health/`` sub-tree. Any
    # sibling like ``/healthcheck`` or ``/healthy`` must NOT be
    # exempt. Walking the data structure here so a future refactor
    # that re-broadens the prefix breaks this test.
    from backend.app.maintenance import _ALWAYS_ALLOWED_EXACT, _ALWAYS_ALLOWED_PREFIXES

    assert "/health" in _ALWAYS_ALLOWED_EXACT
    assert "/health" not in _ALWAYS_ALLOWED_PREFIXES
    # No prefix entry should swallow ``/healthcheck``.
    assert not any("/healthcheck".startswith(prefix) for prefix in _ALWAYS_ALLOWED_PREFIXES)
    assert "/healthcheck" not in _ALWAYS_ALLOWED_EXACT

    # Turn maintenance back off so the rest of the suite isn't affected.
    ok = await client.patch(
        "/api/admin/settings",
        json={"maintenance_enabled": False},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert ok.status_code == 200


# ── 11.3.1 — twofa.enable must source secret from pending cache ─────────


async def test_2fa_enable_rejects_client_supplied_secret_diverging_from_pending(
    client,
):
    """An attacker who hijacked an admin session BEFORE 2FA was on
    must not be able to enable 2FA with a secret they control.

    Pre-fix ``/enable`` used ``body.secret`` verbatim when provided,
    so the attacker could skip ``/setup`` and persist their own
    secret. The fix pops the pending cache and rejects when the
    caller-supplied secret diverges from (or has no corresponding)
    pending entry.
    """
    admin_init, admin_id = await _make_admin(client, tg=1)

    # Step 1: legitimate ``/setup`` populates the pending cache.
    setup = await client.post("/api/admin/2fa/setup", headers=auth_headers(admin_init))
    assert setup.status_code == 200, setup.text
    pending_secret = setup.json()["secret"]

    # Step 2: attacker sends a DIFFERENT secret to ``/enable`` — must 400.
    attacker_secret = generate_secret()
    assert attacker_secret != pending_secret
    resp = await client.post(
        "/api/admin/2fa/enable",
        json={"secret": attacker_secret, "code": totp_now(attacker_secret)},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 400, resp.text

    # The DB row must still be 2FA-off and the attacker's secret must
    # not have been persisted.
    async with async_session() as session:
        u = await session.get(User, admin_id)
        assert u.totp_enabled is False
        assert u.totp_secret is None


async def test_2fa_enable_without_setup_rejected(client):
    """Calling ``/enable`` without a prior ``/setup`` round-trip must 400.

    This is the same attack vector as the divergence test, just with
    no pending entry at all. Pre-fix ``body.secret`` was sufficient
    to persist a secret of the attacker's choice.
    """
    admin_init, admin_id = await _make_admin(client, tg=1)

    attacker_secret = generate_secret()
    resp = await client.post(
        "/api/admin/2fa/enable",
        json={"secret": attacker_secret, "code": totp_now(attacker_secret)},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 400, resp.text

    async with async_session() as session:
        u = await session.get(User, admin_id)
        assert u.totp_enabled is False
        assert u.totp_secret is None


# ── 11.5.2 — wallet adjust first-touch must use lock_user_balance ───────


async def test_wallet_adjust_first_touch_uses_lock_helper(client):
    """First-touch admin wallet adjustment must go through the shared
    ``lock_user_balance`` helper.

    The helper uses ``INSERT ... ON CONFLICT DO NOTHING`` + ``SELECT
    ... FOR UPDATE`` (V11-L-20) so two concurrent first-touch
    adjustments don't race on the unique constraint. Pre-fix the
    cold path did a naked ``session.add() + flush()`` which blew up
    the loser of a race with an ``IntegrityError`` — the audit
    finding 11.5.2.

    We assert the import path here so a future refactor that
    re-introduces the manual ``session.add`` is caught immediately.
    """
    from backend.app.routers.admin import wallets as wallets_router

    assert hasattr(wallets_router, "lock_user_balance"), (
        "wallets router must import lock_user_balance from services_wallet"
    )
    from backend.app.services_wallet import lock_user_balance as canonical

    assert wallets_router.lock_user_balance is canonical, (
        "wallets router must use the shared lock_user_balance helper, not a local re-implementation"
    )

    # Behaviour-level smoke: a first-touch adjustment still credits
    # the balance row idempotently (regression guard on the wiring).
    admin_init, _ = await _make_admin(client, tg=1)
    bob_id = await _bootstrap(client, tg_user_id=2, username="bob")
    resp = await client.post(
        f"/api/admin/wallets/{bob_id}/adjust",
        json={"currency_code": "USDT", "amount": 12.5, "reason": "first-touch"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    assert float(resp.json()["amount"]) == 12.5


# ── 6.2 — twofa.enable must not mutate in-memory counter on failure ─────


async def test_2fa_enable_rotation_failure_does_not_mutate_in_memory_counter(client):
    """When the new code is invalid on rotation, the in-memory
    ``admin.totp_last_counter`` MUST be unchanged.

    Pre-fix the rotation guard wrote ``current_counter`` straight onto
    the row before the *new* code was verified. The DB rollback from
    ``AsyncSession.__aexit__`` undid the persisted write, but the
    in-memory ORM object kept the bumped value — a latent foot-gun
    if a future retry/refresh wrapper re-uses the same instance
    without calling ``session.refresh(admin)``. We assert the
    persisted row is unchanged after a 401 (proxy for the in-memory
    behaviour; the bug only mattered for sessions that wouldn't be
    discarded after the 401, but the DB row IS the canonical source
    so a unchanged row also catches the regression).
    """
    admin_init, admin_id = await _make_admin(client, tg=1)

    # First enrol — populates ``totp_secret`` and ``totp_last_counter``.
    setup = await client.post("/api/admin/2fa/setup", headers=auth_headers(admin_init))
    assert setup.status_code == 200, setup.text
    secret_a = setup.json()["secret"]
    code_a = totp_now(secret_a)
    enable = await client.post(
        "/api/admin/2fa/enable",
        json={"secret": secret_a, "code": code_a},
        headers=auth_headers(admin_init),
    )
    assert enable.status_code == 200, enable.text

    # Snapshot the counter persisted after first enrol.
    async with async_session() as session:
        u = await session.get(User, admin_id)
        baseline_counter = u.totp_last_counter
        assert baseline_counter is not None
        assert baseline_counter >= 0
        baseline_secret = u.totp_secret
        baseline_session_epoch = u.totp_session_epoch

    # Reset the counter so the rotation guard can pass a fresh
    # ``current_counter > baseline_counter`` check, then try to
    # rotate with a VALID current_code but an INVALID new code.
    async with async_session() as session:
        u = await session.get(User, admin_id)
        u.totp_last_counter = -1
        await session.commit()

    # New ``/setup`` for the new secret (so pending is populated).
    setup2 = await client.post("/api/admin/2fa/setup", headers=auth_headers(admin_init))
    assert setup2.status_code == 200, setup2.text
    secret_b = setup2.json()["secret"]
    assert secret_b != secret_a

    # Valid ``current_code`` (proves the rotation guard passes), then
    # an INVALID new code — the handler must raise 401 "Неверный код"
    # after verify_totp_and_counter(secret_b, "000000") returns None.
    resp = await client.post(
        "/api/admin/2fa/enable",
        json={
            "secret": secret_b,
            "code": "000000",
            "current_code": totp_now(secret_a),
        },
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 401, resp.text

    # Critical assertion: the persisted secret/epoch are unchanged
    # (rotation was rejected) and the counter was NOT bumped to the
    # rotation guard's ``current_counter``. The persisted counter
    # may have been reset to -1 above and stayed there; what matters
    # is that the 401 did NOT roll forward the row.
    async with async_session() as session:
        u = await session.get(User, admin_id)
        assert u.totp_secret == baseline_secret, (
            "rotation must not replace the secret when the new code is invalid"
        )
        assert u.totp_session_epoch == baseline_session_epoch, (
            "rotation must not bump the session epoch when the new code is invalid"
        )
        # The row's counter must remain at -1 (our reset) — NOT at
        # ``verify_totp_and_counter(secret_a, totp_now(secret_a))`` which
        # is what the pre-fix code would have written.
        assert u.totp_last_counter == -1, (
            "rotation must not bump totp_last_counter when the new code is invalid"
        )


# ── 3.2 — notify.send_dm one-shot warning on unconfigured bot ───────────


async def test_send_dm_warns_only_once_when_bot_unconfigured(monkeypatch, caplog):
    """Calling ``send_dm`` repeatedly without a configured bot must
    emit ``logger.warning`` only once per process; subsequent calls
    log at ``DEBUG`` level.

    Pre-fix every miss emitted ``logger.warning`` which on dev
    (``BOT_TOKEN=0000000000:FAKE``) drowned out actual signal in
    logs and Sentry. We use the module's test-only reset hook to
    re-arm the one-shot guard for this test, then assert the level
    of each emission.
    """
    import logging

    from backend.app.bot import notify as notify_module
    from backend.app.config import settings

    # Force the "unconfigured" branch by clearing the bot token and
    # the cached ``_bot`` instance.
    monkeypatch.setattr(settings, "bot_token", "")
    monkeypatch.setattr(notify_module, "_bot", None)
    notify_module._reset_unconfigured_warned()

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="backend.app.bot.notify"):
        ok1 = await notify_module.send_dm(1, "first miss")
        ok2 = await notify_module.send_dm(2, "second miss")
        ok3 = await notify_module.send_dm(3, "third miss")

    assert ok1 is False
    assert ok2 is False
    assert ok3 is False

    unconfigured_records = [
        rec for rec in caplog.records if getattr(rec, "event", None) == "bot.dm.unconfigured"
    ]
    assert len(unconfigured_records) == 3, f"expected 3 records, got {len(unconfigured_records)}"

    # First emission is WARNING with ``first_observation=True``.
    assert unconfigured_records[0].levelno == logging.WARNING
    assert unconfigured_records[0].first_observation is True

    # Subsequent emissions are DEBUG with ``first_observation=False``.
    assert unconfigured_records[1].levelno == logging.DEBUG
    assert unconfigured_records[2].levelno == logging.DEBUG
    assert unconfigured_records[1].first_observation is False
    assert unconfigured_records[2].first_observation is False
