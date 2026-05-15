"""V5-A — security/auth follow-ups regression suite.

One pricked test per fix in the V5-A audit bucket. Each ``async def``
maps to an entry in ``audit-status-v8.md §2.B``:

* V5-A-2 — empty-hash invariant in ``security.verify_init_data``.
* V5-A-3 — ``_parse_unsigned`` refuses to run in production/staging
  even if the boot guard was bypassed.
* V5-A-4 — common-PIN blacklist at ``/setup``, ``/change``, and
  ``/reset/confirm``. Also asserts the ordering invariants:
  wrong-old-PIN returns 401 before the strength check, and
  wrong-reset-code returns 401 before the strength check (so
  attackers can't probe the new-PIN field).
* V5-A-5 — ``_ensure_format`` runs before ``_is_locked`` so a
  locked-but-malformed payload returns 400, not 423.
* V5-A-9 — ``ADMIN_TOTP_BYPASS`` is re-read per-request (not cached
  at module load).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.app.auth_2fa import _totp_bypass
from backend.app.db import async_session
from backend.app.models import User
from backend.app.security import InitDataError, verify_init_data
from tests.helpers import (
    STRONG_TEST_PIN,
    auth_headers,
    setup_pin,
    signed_init_data,
)

# ── V5-A-2 — empty-hash invariant ───────────────────────────────────────


def test_verify_init_data_rejects_empty_hash(monkeypatch):
    """``hash=`` (empty value) must be rejected the same as a missing
    ``hash`` field. Otherwise a degenerate query string with an empty
    HMAC could slip past the ``if not received_hash`` short-circuit
    into ``hmac.compare_digest``, which compares against a non-empty
    hexdigest and always returns False — but we don't want to silently
    rely on that defence-in-depth fallback.
    """
    # ``ALLOW_UNSIGNED_INIT_DATA`` would short-circuit into
    # ``_parse_unsigned`` and never hit the hash check; force the
    # signed path.
    from backend.app.config import settings

    monkeypatch.setattr(settings, "allow_unsigned_init_data", False)
    monkeypatch.setattr(settings, "bot_token", "test-bot-token")

    with pytest.raises(InitDataError, match="hash is missing"):
        verify_init_data("user=%7B%22id%22%3A1%7D&auth_date=1700000000&hash=")

    with pytest.raises(InitDataError, match="hash is missing"):
        verify_init_data("user=%7B%22id%22%3A1%7D&auth_date=1700000000")


# ── V5-A-3 — _parse_unsigned defence-in-depth ───────────────────────────


def test_parse_unsigned_refuses_in_production(monkeypatch):
    """Even if ``ALLOW_UNSIGNED_INIT_DATA`` is somehow True in a
    production-grade environment (e.g. a misconfigured test fixture
    or an ``app`` imported without running ``lifespan``), the parser
    must refuse rather than auth-ing as an arbitrary user.
    """
    from backend.app.config import settings

    monkeypatch.setattr(settings, "allow_unsigned_init_data", True)
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(InitDataError, match="rejected outside development"):
        verify_init_data('{"id": 1, "first_name": "x"}')

    monkeypatch.setattr(settings, "environment", "staging")
    with pytest.raises(InitDataError, match="rejected outside development"):
        verify_init_data('{"id": 1, "first_name": "x"}')

    # Dev still works.
    monkeypatch.setattr(settings, "environment", "development")
    payload = verify_init_data('{"id": 1, "first_name": "x"}')
    assert payload["id"] == 1


# ── V5-A-4 — common-PIN blacklist at all three commit points ────────────


async def test_pin_setup_rejects_common_pin(client):
    """``/setup`` must 400 every PIN in the blacklist.

    /setup is itself per-user rate-limited (RLPin = 5/min), so we
    reset the limiter buckets between attempts and use only a
    representative sample of the blacklist (the unit-level
    blacklist invariant is covered by
    :func:`test_common_pins_membership` below).
    """
    from backend.app.rate_limit import reset_state_for_tests

    init = signed_init_data(7001, "common_setup")
    for weak in ("1234", "0000", "1111", "2580"):
        reset_state_for_tests()
        resp = await client.post(
            "/api/pin/setup",
            json={"pin": weak},
            headers=auth_headers(init),
        )
        assert resp.status_code == 400, f"{weak} accepted: {resp.text}"
        assert "слишком простой" in resp.json().get("detail", "").lower()


def test_common_pins_membership():
    """Unit-level invariant: the blacklist covers all 10 single-digit
    repeats plus the canonical 1234/4321/2580/etc set from the audit.
    """
    from backend.app.pin import COMMON_PINS, is_pin_too_common

    for d in range(10):
        repeat = str(d) * 4
        assert is_pin_too_common(repeat), f"{repeat} missing from blacklist"

    for canonical in ("1234", "0123", "4321", "9876", "2580", "1004"):
        assert is_pin_too_common(canonical), f"{canonical} missing"

    # Strong PINs that pass.
    for strong in ("3741", "5837", "4163", "5092", "7592"):
        assert not is_pin_too_common(strong), f"{strong} falsely blacklisted"

    assert "3741" not in COMMON_PINS  # belt + braces


async def test_pin_setup_accepts_strong_pin(client):
    """Sanity-check: ``setup_pin`` helper's default (STRONG_TEST_PIN)
    plus another randomly-chosen strong PIN both pass.
    """
    init1 = signed_init_data(7011, "strong1")
    tok = await setup_pin(client, init1, pin=STRONG_TEST_PIN)
    assert tok

    init2 = signed_init_data(7012, "strong2")
    resp = await client.post(
        "/api/pin/setup",
        json={"pin": "5837"},  # not in blacklist
        headers=auth_headers(init2),
    )
    assert resp.status_code == 200, resp.text


async def test_pin_change_rejects_common_new_pin(client):
    """``/change`` must 400 if ``new_pin`` is common — and crucially
    *after* verifying ``old_pin``, so that strength rejection happens
    only on the happy path. We assert both:

    1. Common ``new_pin`` with correct ``old_pin`` → 400 (strength).
    2. Common ``new_pin`` with wrong ``old_pin`` → 401 (wrong PIN),
       NOT 400. This is the leak-prevention invariant from
       :func:`_ensure_strong`'s docstring.
    """
    init = signed_init_data(7002, "common_change")
    await setup_pin(client, init, pin=STRONG_TEST_PIN)

    # Happy path: correct old_pin, weak new_pin → 400 strength.
    resp = await client.post(
        "/api/pin/change",
        json={"old_pin": STRONG_TEST_PIN, "new_pin": "1234"},
        headers=auth_headers(init),
    )
    assert resp.status_code == 400, resp.text
    assert "слишком простой" in resp.json().get("detail", "").lower()

    # PIN must NOT have been changed.
    async with async_session() as session:
        user = (await session.execute(select(User).where(User.tg_user_id == 7002))).scalar_one()
        # Successful happy path resets attempts; this branch should NOT
        # have bumped them either (strength check is before attempts++).
        assert (user.pin_attempts or 0) == 0

    # Probe: wrong old_pin + weak new_pin → still 401 (not 400).
    # This is V5-A-4's no-leak invariant.
    probe = await client.post(
        "/api/pin/change",
        json={"old_pin": "9999", "new_pin": "1234"},
        headers=auth_headers(init),
    )
    assert probe.status_code == 401, probe.text


async def test_pin_reset_confirm_rejects_common_new_pin(client, monkeypatch):
    """Same ordering invariant as ``/change`` but for the reset flow:

    * Wrong reset code + weak new_pin → 401 (consumes one /check
      attempt, doesn't probe strength).
    * Correct reset code + weak new_pin → 400 strength rejection
      (the reset code is still consumed via persistence, so the user
      has to request a fresh code to retry).
    """
    import backend.app.routers.pin as pin_mod

    async def _noop(*_args, **_kwargs):
        return True

    monkeypatch.setattr(pin_mod, "send_dm", _noop)

    init = signed_init_data(7003, "common_reset")
    await setup_pin(client, init, pin=STRONG_TEST_PIN)

    # Mint a reset code.
    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(pin_mod, "send_dm", sent)
    # Capture the code via a generate_reset_code spy.
    SENTINEL = "424242"
    monkeypatch.setattr(pin_mod, "generate_reset_code", lambda: SENTINEL)
    resp = await client.post(
        "/api/pin/reset/request",
        headers=auth_headers(init),
    )
    assert resp.status_code == 200, resp.text

    # Probe 1: wrong code + weak new_pin → 401, not 400.
    probe = await client.post(
        "/api/pin/reset/confirm",
        json={"code": "000000", "new_pin": "1234"},
        headers=auth_headers(init),
    )
    assert probe.status_code == 401, probe.text

    # Probe 2: correct code + weak new_pin → 400 strength.
    weak = await client.post(
        "/api/pin/reset/confirm",
        json={"code": SENTINEL, "new_pin": "1234"},
        headers=auth_headers(init),
    )
    assert weak.status_code == 400, weak.text
    assert "слишком простой" in weak.json().get("detail", "").lower()


# ── V5-A-5 — format check before lock check ─────────────────────────────


async def test_pin_check_format_400_takes_precedence_over_lock(client):
    """A locked user sending a malformed (non-digit) PIN must see 400,
    not 423. ``_ensure_format`` runs before ``_is_locked`` exactly so
    we don't conflate "client sent garbage" with "user is locked out".
    """
    init = signed_init_data(7004, "fmt_vs_lock")
    await setup_pin(client, init, pin=STRONG_TEST_PIN)

    # Drive the user into the locked state by exhausting attempts.
    from backend.app.config import settings as app_settings

    for _ in range(app_settings.pin_max_attempts):
        await client.post(
            "/api/pin/check",
            json={"pin": "0000"},
            headers=auth_headers(init),
        )

    # Now locked. A garbage payload still gets 400.
    resp = await client.post(
        "/api/pin/check",
        json={"pin": "abcd"},
        headers=auth_headers(init),
    )
    assert resp.status_code == 400, resp.text


# ── V5-A-9 — ADMIN_TOTP_BYPASS read per-request ─────────────────────────


def test_totp_bypass_re_reads_env_per_call(monkeypatch):
    """``_totp_bypass()`` must reflect the current value of
    ``ADMIN_TOTP_BYPASS`` on every call. The pre-V5-A-9 code
    snapshotted the value at module import, which meant a
    ``monkeypatch.delenv`` inside a test had no effect until the
    process restarted — masking misconfigured-bypass bugs in CI.
    """
    monkeypatch.setenv("ADMIN_TOTP_BYPASS", "first-value")
    assert _totp_bypass() == "first-value"

    monkeypatch.setenv("ADMIN_TOTP_BYPASS", "second-value")
    assert _totp_bypass() == "second-value"

    monkeypatch.delenv("ADMIN_TOTP_BYPASS", raising=False)
    assert _totp_bypass() == ""
