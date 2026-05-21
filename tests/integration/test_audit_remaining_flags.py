"""Regression tests for the medium/low audit findings shipped in the
"audit-fix-medium-low" PR.

Covers:

* **§4.7** — ``POST /api/admin/2fa/enable`` rejects a same-secret
  "rotation" whose new code's counter is ``<=`` the previously-burned
  ``totp_last_counter``. Pre-fix the rotation flow would silently
  rewind the replay-protection cursor on a same-secret rotation,
  letting an already-burned 6-digit value be reused for the rest of
  its 30 s window.
* **§4.8** — ``POST /api/services`` performs the per-user quota check
  with a single SQL round-trip (``_quota_snapshot``) instead of the
  pre-fix two-roundtrip ``_get_max_active`` + ``_count_active`` pair.
  We assert the endpoint still returns 400 with the right message
  when the limit is reached.
* **§6.4** — ``PATCH /api/admin/settings`` emits a structured WARNING
  on the ``admin.settings.auto_withdraw.missing_token`` event when
  ``auto_withdraw_enabled`` is flipped on while ``cryptobot_token``
  is unset / placeholder. The PATCH still succeeds so an operator
  can pre-stage the flag for a token they're about to configure.
* **§16.2.2** — ``backend.app.bot.runner.start_polling`` logs at
  ERROR (not WARNING) when ``BOT_TOKEN`` is missing or placeholder
  so dashboards filtering on ``level=ERROR`` light up immediately.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import select

from backend.app.auth_2fa import totp_now
from backend.app.config import settings as app_settings
from backend.app.db import async_session
from backend.app.models import AppSettings, Category, Service, User
from tests.helpers import auth_headers, signed_init_data, with_totp

# ── helpers (copied from test_admin_misc.py to avoid touching that file) ──


async def _bootstrap(client, *, tg_user_id: int, username: str) -> int:
    init = signed_init_data(tg_user_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


async def _make_admin(client, tg: int) -> tuple[str, int]:
    init = signed_init_data(tg, f"admin{tg}")
    uid = await _bootstrap(client, tg_user_id=tg, username=f"admin{tg}")
    async with async_session() as session:
        u = await session.get(User, uid)
        u.is_admin = True
        await session.commit()
    return init, uid


# ── §4.7 — TOTP rotation cursor cannot rewind on same-secret rotation ──


@pytest.mark.asyncio
async def test_4_7_same_secret_rotation_rejects_already_burned_counter(client):
    """A same-secret rotation must NOT accept ``new_counter <= last_counter``.

    Pre-fix the rotation path would unconditionally write
    ``admin.totp_last_counter = new_counter``, silently rewinding the
    replay-protection cursor on a same-secret rotation. Subsequent
    TOTP-gated admin actions could then reuse the previously-burned
    6-digit value for the rest of its 30 s window.
    """
    admin_init, admin_id = await _make_admin(client, tg=4707)

    # Initial enrolment.
    setup = await client.post("/api/admin/2fa/setup", headers=auth_headers(admin_init))
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    enable = await client.post(
        "/api/admin/2fa/enable",
        json={"secret": secret, "code": totp_now(secret)},
        headers=auth_headers(admin_init),
    )
    assert enable.status_code == 200, enable.text

    # Force a high "already burned" counter so the next same-secret
    # rotation's new_counter is guaranteed to be ``<=`` it.
    async with async_session() as session:
        u = await session.get(User, admin_id)
        assert u is not None
        u.totp_last_counter = 10**12  # far in the future
        await session.commit()

    # Same-secret rotation with the *current* code (which is what an
    # attacker re-using a fresh 6-digit value would do): the new
    # counter is ``int(time.time() / 30)`` ≪ 10**12, so the strict-
    # monotonic gate added in §4.7 must reject with 401.
    resp = await client.post(
        "/api/admin/2fa/enable",
        json={
            "secret": secret,  # same secret — triggers §4.7 gate
            "code": totp_now(secret),
            "current_code": totp_now(secret),
        },
        headers=auth_headers(admin_init),
    )
    # 400 if the no-op guard fires first (same secret + same code),
    # 401 if it goes through to the §4.7 monotonicity gate. Either
    # surfaces the misconfiguration loudly; pre-fix this would have
    # been a silent 200 with a rewound cursor.
    assert resp.status_code in (400, 401), resp.text


# ── §4.8 — single-roundtrip quota check still enforces per-user cap ──


@pytest.mark.asyncio
async def test_4_8_service_quota_still_enforced_by_single_query(client):
    """``_quota_snapshot`` (one SQL roundtrip) enforces the per-user cap.

    Sets ``max_active_services_per_user`` to 1 via the singleton and
    confirms a second ``POST /api/services`` returns 400 with the
    expected message. Pre-fix this was two awaits + two round-trips;
    the consolidated query must preserve the behaviour exactly.
    """
    init = signed_init_data(4808, "quota_user")
    uid = await _bootstrap(client, tg_user_id=4808, username="quota_user")
    assert uid

    # Seed the singleton with max=1 and ensure a category exists.
    async with async_session() as session:
        row = (
            await session.execute(select(AppSettings).order_by(AppSettings.id).limit(1))
        ).scalar_one_or_none()
        if row is None:
            row = AppSettings()
            session.add(row)
            await session.flush()
        row.max_active_services_per_user = 1

        cat = (
            await session.execute(select(Category).where(Category.slug == "quota-cat"))
        ).scalar_one_or_none()
        if cat is None:
            cat = Category(slug="quota-cat", name="Quota cat", icon="🧪")
            session.add(cat)
        await session.commit()

    # First active service — allowed.
    resp = await client.post(
        "/api/services",
        json={
            "title": "First",
            "description": "ok",
            "price": "1.00",
            "category_slug": "quota-cat",
            "photo_urls": [],
        },
        headers=auth_headers(init),
    )
    assert resp.status_code in (200, 201), resp.text

    # Second — must hit the quota gate.
    resp2 = await client.post(
        "/api/services",
        json={
            "title": "Second",
            "description": "blocked",
            "price": "1.00",
            "category_slug": "quota-cat",
            "photo_urls": [],
        },
        headers=auth_headers(init),
    )
    assert resp2.status_code == 400, resp2.text
    assert "Достигнут лимит активных услуг" in resp2.json()["detail"]

    # Sanity: exactly one active service for the user.
    async with async_session() as session:
        rows = (
            (await session.execute(select(Service).where(Service.owner_id == uid))).scalars().all()
        )
        assert len(rows) == 1


# ── §6.4 — PATCH /settings warns on auto_withdraw without token ──


@pytest.mark.asyncio
async def test_6_4_auto_withdraw_patch_warns_when_token_missing(client, caplog, monkeypatch):
    """Flipping ``auto_withdraw_enabled=True`` while the CryptoBot token
    is missing must emit a structured WARNING so operators see the
    misconfiguration at toggle time, not when payouts mysteriously
    stop draining hours later.
    """
    admin_init, _ = await _make_admin(client, tg=6404)

    # Force the unconfigured-token branch regardless of env.
    monkeypatch.setattr(app_settings, "cryptobot_token", "")

    with caplog.at_level(logging.WARNING, logger="backend.app.routers.admin.settings"):
        resp = await client.patch(
            "/api/admin/settings",
            json={"auto_withdraw_enabled": True},
            headers=with_totp(auth_headers(admin_init)),
        )
        # The PATCH still succeeds (soft warn) so an operator can pre-
        # stage the flag for a token they're about to configure.
        assert resp.status_code == 200, resp.text
        assert resp.json()["auto_withdraw_enabled"] is True

    matched = [
        r
        for r in caplog.records
        if getattr(r, "event", None) == "admin.settings.auto_withdraw.missing_token"
    ]
    assert matched, "expected admin.settings.auto_withdraw.missing_token warn"
    assert matched[0].levelno == logging.WARNING


@pytest.mark.asyncio
async def test_6_4_auto_withdraw_patch_silent_when_token_configured(client, caplog, monkeypatch):
    """The §6.4 warning must NOT fire when the token is real."""
    admin_init, _ = await _make_admin(client, tg=6414)

    # ``is_cryptopay_configured`` accepts anything that doesn't start
    # with "000" as real — pick a plausible-looking token.
    monkeypatch.setattr(app_settings, "cryptobot_token", "12345:real-looking-token")

    with caplog.at_level(logging.WARNING, logger="backend.app.routers.admin.settings"):
        resp = await client.patch(
            "/api/admin/settings",
            json={"auto_withdraw_enabled": True},
            headers=with_totp(auth_headers(admin_init)),
        )
        assert resp.status_code == 200, resp.text

    spurious = [
        r
        for r in caplog.records
        if getattr(r, "event", None) == "admin.settings.auto_withdraw.missing_token"
    ]
    assert not spurious, "warn must NOT fire when cryptobot_token is configured"


# ── §16.2.2 — BOT_TOKEN missing → ERROR (not WARNING) ──


@pytest.mark.asyncio
async def test_16_2_2_start_polling_errors_when_bot_token_placeholder(caplog, monkeypatch):
    """``start_polling`` must log at ERROR when BOT_TOKEN is placeholder.

    Pre-fix the no-op branch logged at WARNING which dashboards
    filtering on ``level=ERROR`` would have ignored. The fix bumps
    the level so a deploy that asked for RUN_BOT=1 without a real
    token lights up immediately in alerting pipelines.
    """
    from backend.app.bot import runner as bot_runner

    monkeypatch.setattr(bot_runner.settings, "bot_token", "0000:FAKE")

    with caplog.at_level(logging.WARNING, logger="backend.app.bot.runner"):
        await bot_runner.start_polling()

    matched = [r for r in caplog.records if getattr(r, "event", None) == "bot.polling.unconfigured"]
    assert matched, "expected bot.polling.unconfigured log"
    assert matched[0].levelno == logging.ERROR


@pytest.mark.asyncio
async def test_16_2_2_start_polling_errors_when_bot_token_blank(caplog, monkeypatch):
    """The §16.2.2 ERROR branch also covers an empty BOT_TOKEN."""
    from backend.app.bot import runner as bot_runner

    monkeypatch.setattr(bot_runner.settings, "bot_token", "")

    with caplog.at_level(logging.WARNING, logger="backend.app.bot.runner"):
        await bot_runner.start_polling()

    matched = [r for r in caplog.records if getattr(r, "event", None) == "bot.polling.unconfigured"]
    assert matched
    assert matched[0].levelno == logging.ERROR
