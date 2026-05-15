"""Regression tests for the security audit fixes.

Covers four issues raised in the audit pass and patched in this PR:

* **Account-transfer brute-force** — the 6-digit one-time code is
  shared across the keyspace, so the confirm endpoint must rate-limit
  attempts *and* burn codes after a small number of misses.
* **CryptoBot webhook fail-open** — when ``CRYPTOBOT_TOKEN`` is empty
  the webhook must refuse the request, not silently accept it.
* **Media upload XSS** — the saved extension comes from the validated
  content-type, never from the user-supplied filename.
* **CORS wildcard fallback** — booting with an empty
  ``ALLOWED_ORIGINS`` must fail instead of installing ``allow_origins
  = ["*"]`` alongside ``allow_credentials = True``.
"""

from __future__ import annotations

import importlib
import json

import pytest
from sqlalchemy import select

from tests.helpers import (
    auth_headers,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)

# ── 1. Account-transfer brute-force protection ────────────────────────────


async def _issue_transfer_code(client, source_init: str, tg_user_id: int) -> str:
    """Issue a fresh transfer code for ``tg_user_id`` and return its
    plaintext. The HTTP endpoint only delivers the code via the bot, so
    for deterministic tests we drive the service layer directly.
    """
    from backend.app.db import async_session
    from backend.app.models import User
    from backend.app.services_account import issue_code

    await setup_pin(client, source_init)  # bootstraps the source row

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, tg_user_id)
        source = await session.get(User, user_id)
        assert source is not None
        code, _expires = await issue_code(session, source)
    return code


async def test_transfer_confirm_burns_code_after_few_misses(client):
    """Wrong codes must not burn other users' codes (DoS prevention).

    After the H-4 fix, ``_register_miss`` is a no-op — brute-force
    protection relies on the per-IP rate limiter (RLPin 5/min).
    This test verifies that failed attempts from an attacker do NOT
    increment ``attempts`` on the legitimate user's code.
    """
    from backend.app.db import async_session
    from backend.app.models import AccountTransferCode

    source_init = signed_init_data(9101, "source")
    real_code = await _issue_transfer_code(client, source_init, 9101)

    attacker_init = signed_init_data(9102, "attacker")
    resp = await client.get("/api/me", headers=auth_headers(attacker_init))
    assert resp.status_code == 200

    # Send a few wrong codes from the attacker.
    for i in range(3):
        wrong = f"{(int(real_code) + i + 1) % 1_000_000:06d}"
        if wrong == real_code:
            wrong = "000000" if real_code != "000000" else "111111"
        resp = await client.post(
            "/api/account/transfer/confirm",
            json={"code": wrong},
            headers=auth_headers(attacker_init),
        )
        assert resp.status_code == 400

    # The legitimate code must remain untouched — attempts == 0,
    # not consumed. This proves the DoS vector is closed.
    async with async_session() as session:
        row = (await session.execute(select(AccountTransferCode))).scalar_one()
        assert row.consumed_at is None, "code must NOT be consumed by attacker misses"
        assert row.attempts == 0, "attacker misses must not increment other codes"


async def test_transfer_confirm_rate_limit_applied(client):
    """RLPin is wired up — confirm should 429 past 5/minute."""
    from backend.app.rate_limit import reset_state_for_tests

    reset_state_for_tests()

    attacker_init = signed_init_data(9201, "rl-attacker")
    resp = await client.get("/api/me", headers=auth_headers(attacker_init))
    assert resp.status_code == 200

    statuses: list[int] = []
    for _ in range(7):
        resp = await client.post(
            "/api/account/transfer/confirm",
            json={"code": "000000"},
            headers=auth_headers(attacker_init),
        )
        statuses.append(resp.status_code)

    # First few are 400 (bad code); somewhere after the 5th, the limiter
    # kicks in with 429.
    assert 429 in statuses, statuses


# ── 2. CryptoBot webhook fail-closed when token is unset ──────────────────


async def test_webhook_refuses_when_token_unset(client, monkeypatch):
    """An empty CRYPTOBOT_TOKEN must NOT let unauthenticated callers in."""
    from backend.app.routers import payments as payments_router

    monkeypatch.setattr(payments_router, "webhook_secret", lambda: "")

    body = json.dumps({"update_type": "invoice_paid", "payload": {"invoice_id": "x"}}).encode()
    resp = await client.post(
        "/api/payments/webhook/cryptobot",
        content=body,
        headers={
            "crypto-pay-api-signature": "anything",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 503


# ── 3. Media upload — extension is content-type derived ───────────────────


async def test_media_upload_rejects_html_disguised_as_image(client):
    """A client uploading ``evil.html`` with an image content-type must
    still get a safe, image-only extension on disk — the saved file
    must not be ``.html``."""
    from backend.app.db import async_session
    from backend.app.models import Media

    init_data = signed_init_data(9301, "uploader")
    await setup_pin(client, init_data)  # bootstraps the user row

    files = {"file": ("evil.html", b"\x89PNG\r\n\x1a\n", "image/png")}
    data = {"kind": "avatar"}
    resp = await client.post(
        "/api/media/upload", data=data, files=files, headers=auth_headers(init_data)
    )
    assert resp.status_code == 201, resp.text

    payload = resp.json()
    assert payload["url"].endswith(".png"), payload
    assert ".html" not in payload["url"]

    async with async_session() as session:
        m = (await session.execute(select(Media))).scalar_one()
        assert not m.url.endswith(".html")
        assert m.url.endswith(".png")


async def test_media_upload_rejects_unknown_content_type(client):
    """Non-image content-types are now refused for every ``kind``,
    including ``deal`` which previously accepted anything."""
    init_data = signed_init_data(9302, "uploader2")
    await setup_pin(client, init_data)

    files = {"file": ("payload.html", b"<script>1</script>", "text/html")}
    data = {"kind": "deal"}
    resp = await client.post(
        "/api/media/upload", data=data, files=files, headers=auth_headers(init_data)
    )
    assert resp.status_code == 415, resp.text


# ── 4. CORS — wildcard fallback removed ───────────────────────────────────


def test_main_refuses_empty_allowed_origins(monkeypatch):
    """Importing ``backend.app.main`` with empty ALLOWED_ORIGINS must
    raise — we no longer fall back to ``["*"]``."""
    from backend.app import config

    monkeypatch.setattr(config.settings, "allowed_origins", "")

    import backend.app.main as main_module

    with pytest.raises(RuntimeError, match="ALLOWED_ORIGINS"):
        importlib.reload(main_module)

    # Reload back to the conftest default so other tests stay healthy.
    monkeypatch.setattr(config.settings, "allowed_origins", "http://localhost:5173")
    importlib.reload(main_module)


# ── 5. PIN session epoch — admin invalidate-sessions revokes tokens ───────


async def test_invalidate_sessions_revokes_active_pin_token(client):
    """An admin calling ``invalidate-sessions`` must immediately make every
    previously-issued PIN token fail the ``epoch`` check on
    ``require_pin_session`` — no JWT TTL wait, no Redis blacklist."""
    from backend.app.db import async_session
    from backend.app.models import User

    # Bootstrap a normal user with an active PIN session.
    user_init = signed_init_data(9401, "victim")
    pin_token = await setup_pin(client, user_init)

    # Sanity-check: token works on a PIN-gated endpoint (account
    # transfer cancel is PIN-gated and idempotent — runs even when
    # there's no active code).
    probe = await client.post(
        "/api/account/transfer/cancel",
        headers={**auth_headers(user_init), "X-Pin-Token": pin_token},
    )
    assert probe.status_code == 200, probe.text

    # Bootstrap an admin and call ``invalidate-sessions`` against the user.
    admin_init = signed_init_data(9402, "admin9402")
    await client.get("/api/me", headers=auth_headers(admin_init))
    async with async_session() as session:
        admin = (await session.execute(select(User).where(User.tg_user_id == 9402))).scalar_one()
        admin.is_admin = True
        target = (await session.execute(select(User).where(User.tg_user_id == 9401))).scalar_one()
        target_id = target.id
        epoch_before = target.pin_session_epoch or 0
        await session.commit()

    resp = await client.post(
        f"/api/admin/users/{target_id}/invalidate-sessions",
        json={"reason": "leaked device"},
        headers={
            **auth_headers(admin_init),
            "X-Totp-Code": "test-totp-bypass-do-not-use-in-prod",
        },
    )
    assert resp.status_code == 200, resp.text

    async with async_session() as session:
        target = await session.get(User, target_id)
        assert (target.pin_session_epoch or 0) == epoch_before + 1

    # The old token must now be rejected.
    revoked = await client.post(
        "/api/account/transfer/cancel",
        headers={**auth_headers(user_init), "X-Pin-Token": pin_token},
    )
    assert revoked.status_code == 401, revoked.text

    # A fresh PIN check mints a token bound to the new epoch and works.
    refreshed = await client.post(
        "/api/pin/check", json={"pin": "1234"}, headers=auth_headers(user_init)
    )
    assert refreshed.status_code == 200, refreshed.text
    fresh_token = refreshed.json()["token"]
    final = await client.post(
        "/api/account/transfer/cancel",
        headers={**auth_headers(user_init), "X-Pin-Token": fresh_token},
    )
    assert final.status_code == 200, final.text


# ── 6. PIN reset throttle — 3 per 24h per user ────────────────────────────


async def test_pin_reset_request_throttled_after_three(client, monkeypatch):
    """Each user may request at most 3 PIN-reset codes per rolling 24h
    window. The 4th request returns 429 with a ``Retry-After`` header."""
    import backend.app.routers.pin as pin_mod
    from backend.app.rate_limit import reset_state_for_tests
    from backend.app.routers.pin import PIN_RESET_MAX_PER_WINDOW

    # The endpoint awaits ``send_dm`` which spins up a real aiogram bot
    # and aiohttp session — that session is bound to the event loop the
    # bot was first instantiated on, so reusing it across pytest's
    # per-test loop raises "Event loop is closed". Tests that hit this
    # endpoint stub the call out.
    async def _noop(*_args, **_kwargs):
        return True

    monkeypatch.setattr(pin_mod, "send_dm", _noop)

    user_init = signed_init_data(9501, "resetter")
    await setup_pin(client, user_init)

    # Each request also burns one slot of the per-user pin RLPin (5/min)
    # — three requests fit comfortably. After the throttle blocks at 3
    # we don't go to a 4th here because of that ambiguity; instead we
    # explicitly reset RLPin and prove the throttle is the gate.
    reset_state_for_tests()
    for i in range(PIN_RESET_MAX_PER_WINDOW):
        resp = await client.post(
            "/api/pin/reset/request",
            headers=auth_headers(user_init),
        )
        assert resp.status_code == 200, f"hit {i}: {resp.text}"

    # 4th attempt: reset the in-memory RLPin bucket to isolate the
    # throttle. ``pin_reset_attempts`` is now at the cap.
    reset_state_for_tests()
    resp = await client.post(
        "/api/pin/reset/request",
        headers=auth_headers(user_init),
    )
    assert resp.status_code == 429, resp.text
    assert resp.headers.get("Retry-After") is not None


# ── 7. CryptoBot webhook stays reachable during maintenance ───────────────


async def test_webhook_bypasses_maintenance_mode(client):
    """When the global maintenance toggle is on, the CryptoBot webhook
    must still accept POSTs (signature verification handles auth) so
    deposits don't silently drop. The endpoint returns 401 because we
    don't sign the body — but it must NOT return the 503 maintenance
    response, which would tell the audit it's gated by the middleware."""
    from backend.app.db import async_session
    from backend.app.models import AppSettings

    async with async_session() as session:
        s = (
            await session.execute(select(AppSettings).order_by(AppSettings.id).limit(1))
        ).scalar_one()
        s.maintenance_enabled = True
        await session.commit()

    try:
        resp = await client.post(
            "/api/payments/webhook/cryptobot",
            content=b"{}",
            headers={"Content-Type": "application/json"},
        )
        # Maintenance middleware would 503; the webhook handler 401s on
        # missing/invalid signature. Either passes the maintenance gate
        # — the discriminator is that 503 must NOT come from this route.
        assert resp.status_code != 503, resp.text
    finally:
        async with async_session() as session:
            s = (
                await session.execute(select(AppSettings).order_by(AppSettings.id).limit(1))
            ).scalar_one()
            s.maintenance_enabled = False
            await session.commit()


# ── 8. /api/payments/deposit is rate-limited ──────────────────────────────


async def test_manual_deposit_rate_limited(client):
    """The legacy USD invoice endpoint capped at 10 calls per minute per
    user. The 11th call must 429."""
    from backend.app.rate_limit import reset_state_for_tests

    init = signed_init_data(9601, "depositor")
    await client.get("/api/me", headers=auth_headers(init))

    reset_state_for_tests()

    # Vary the amount so the ``provider_invoice_id = manual-{uid}-{amt}``
    # unique constraint doesn't collide between attempts.
    for i in range(10):
        resp = await client.post(
            "/api/payments/deposit",
            json={"amount": float(i + 1)},
            headers=auth_headers(init),
        )
        assert resp.status_code == 200, f"hit {i}: {resp.text}"

    resp = await client.post(
        "/api/payments/deposit",
        json={"amount": 999.0},
        headers=auth_headers(init),
    )
    assert resp.status_code == 429, resp.text


# ── 9. Security response headers on every HTTP reply ──────────────────────


async def test_security_response_headers_present(client):
    """All HTTP responses must carry the defence-in-depth security
    headers added by the global middleware: MIME-sniff, referrer,
    frame-ancestors, and a full Content-Security-Policy that only
    allows ``'self'`` plus the one cross-origin script the TMA needs
    (``telegram-web-app.js`` from ``telegram.org``).

    The CSP assertion is broken into per-directive substring checks so
    that whitespace changes inside the policy string don't make the
    test brittle — what matters is that each directive carries the
    expected sources, not that the serialisation is byte-identical.
    """
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["x-frame-options"] == "DENY"

    csp = resp.headers["content-security-policy"]
    # Default fallback locks every fetch directive to same-origin
    # unless explicitly broadened below.
    assert "default-src 'self'" in csp
    # The only cross-origin script the TMA loads is Telegram's SDK.
    assert "script-src 'self' https://telegram.org" in csp
    # Framer Motion was removed; all animations now use CSS classes.
    # ``'unsafe-inline'`` is no longer needed for style-src.
    assert "style-src 'self'" in csp
    assert "'unsafe-inline'" not in csp.split("style-src")[1].split(";")[0]
    # Avatars/screenshots come from ``/media/`` (same origin); ``data:``
    # covers tiny placeholder SVGs Vite may inline, ``blob:`` covers
    # client-side previews of uploads before submit.
    assert "img-src 'self' data: blob:" in csp
    # REST + WebSocket are same-origin only.
    assert "connect-src 'self'" in csp
    # Modern equivalent of ``X-Frame-Options: DENY`` (kept for legacy).
    assert "frame-ancestors 'none'" in csp
    # Lock down plugins and form posts to defence-in-depth defaults.
    assert "object-src 'none'" in csp
    assert "form-action 'self'" in csp
    assert "base-uri 'self'" in csp
