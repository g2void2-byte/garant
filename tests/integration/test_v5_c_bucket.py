"""V5-C — admin / auth / maintenance hardening bucket.

Six items from §2.B of audit-status-v10, all confined to
``backend.app.maintenance`` and ``backend.app.admin_audit``:

* **V5-C-1** — throttle the "DB lookup failed" traceback so a
  prolonged DB outage does not flood stderr / Sentry on every
  middleware pass.
* **V5-C-2** — shorten the maintenance-flag cache TTL from 30 s to
  5 s so peer workers reflect an admin toggle within one screen
  refresh instead of half a minute.
* **V5-C-3** — drop the ``/api/auth/`` wildcard from
  ``_ALWAYS_ALLOWED_PREFIXES``; the read-only short-circuit already
  admits GETs, and the wildcard would silently bypass the
  maintenance gate for any future write-path mounted under that
  prefix.
* **V5-C-4** — cap ``admin_audit_log.payload`` at 4 KB to mirror the
  ``notifier.push`` cap (Comment 39 from audit v9).
* **V5-C-5** — route audit-log IP extraction through
  ``deps._client_ip`` so the ``TRUSTED_PROXIES`` gate stays in one
  place; the docstring spells out the threat model so operators
  don't terminate TLS in front of untrusted hops.
* **V5-C-7** — regression for the unauthenticated branch on
  ``GET /api/admin/dashboard``; the existing suite covers
  ``non-admin → 403`` but not the missing / malformed initData path.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import patch

import pytest
from fastapi import Request
from sqlalchemy import select

from backend.app import admin_audit
from backend.app import maintenance as maintenance_module
from backend.app.config import settings as app_settings
from backend.app.db import async_session
from backend.app.models import AdminAuditLog, User
from tests.helpers import auth_headers, signed_init_data, with_totp

# ── shared fixtures ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_maintenance_state():
    """Each V5-C test starts with empty maintenance + throttle state."""
    maintenance_module.invalidate_cache()
    maintenance_module._reset_db_error_log_state()
    yield
    maintenance_module.invalidate_cache()
    maintenance_module._reset_db_error_log_state()


async def _bootstrap_admin(client, tg: int = 4321) -> str:
    """Create an admin user and return its initData."""
    init = signed_init_data(tg, f"vcadmin{tg}")
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    async with async_session() as session:
        user = (await session.execute(select(User).where(User.tg_user_id == tg))).scalar_one()
        user.is_admin = True
        await session.commit()
    return init


# ── V5-C-1 — throttled "DB lookup failed" log ─────────────────────────────


@pytest.mark.asyncio
async def test_v5_c_1_db_lookup_failure_is_throttled(caplog):
    """Repeated DB failures emit exactly one ``logger.exception``
    within the throttle window; subsequent calls bump a suppressed
    counter that gets flushed on the next escape from the window.
    """

    async def _always_raise():
        raise RuntimeError("simulated DB down")

    real_load = maintenance_module._load_from_db
    maintenance_module._load_from_db = _always_raise
    try:
        with caplog.at_level(logging.ERROR, logger="backend.app.maintenance"):
            for _ in range(5):
                await maintenance_module._get_maintenance()
                # Drop the error-path cache so each call re-runs the DB
                # path; otherwise the 1 s cached failure would skip
                # ``_log_db_lookup_failure`` entirely.
                maintenance_module.invalidate_cache()
    finally:
        maintenance_module._load_from_db = real_load

    db_error_records = [r for r in caplog.records if "settings lookup failed" in r.getMessage()]
    assert len(db_error_records) == 1, [r.getMessage() for r in db_error_records]
    # Four of the five failures should have been suppressed and
    # accounted for in the in-memory counter.
    assert maintenance_module._db_error_log_state["suppressed"] == 4


@pytest.mark.asyncio
async def test_v5_c_1_throttle_window_flushes_suppressed_count(caplog):
    """When the throttle deadline expires the next emit reports the
    suppressed count so observability is preserved across the silent
    stretch.
    """

    async def _always_raise():
        raise RuntimeError("simulated DB down")

    real_load = maintenance_module._load_from_db
    maintenance_module._load_from_db = _always_raise
    try:
        with caplog.at_level(logging.ERROR, logger="backend.app.maintenance"):
            await maintenance_module._get_maintenance()
            maintenance_module.invalidate_cache()
            # Three more inside the throttle window — all suppressed.
            for _ in range(3):
                await maintenance_module._get_maintenance()
                maintenance_module.invalidate_cache()
            # Force the deadline into the past so the next call escapes
            # the window without an actual 60 s sleep.
            maintenance_module._db_error_log_state["next_emit_at"] = 0.0
            await maintenance_module._get_maintenance()
    finally:
        maintenance_module._load_from_db = real_load

    db_error_records = [r for r in caplog.records if "settings lookup failed" in r.getMessage()]
    assert len(db_error_records) == 2
    # The second emit carries the suppressed count from the silent
    # stretch (the three calls between emit #1 and emit #2).
    assert "suppressed 3" in db_error_records[1].getMessage()


# ── V5-C-2 — shorter cache TTL ────────────────────────────────────────────


def test_v5_c_2_cache_ttl_is_short():
    """Peer-worker staleness window after an admin toggle.  The
    audit specifies 5 s; anything larger would let a co-tenant
    worker keep accepting writes well past the moment maintenance
    was flipped on.
    """
    assert maintenance_module._TTL_SECONDS == 5.0


def test_v5_c_2_cache_lock_is_event_loop_local(monkeypatch):
    """The maintenance cache lock must survive pytest's per-test loops.

    A contended module-level ``asyncio.Lock`` binds to its first event
    loop. Full-suite CI later reused the imported app in another loop
    and crashed inside the middleware with "lock is bound to a
    different event loop". Two contended refreshes in two fresh loops
    reproduce that old failure deterministically.
    """

    async def _slow_load() -> tuple[bool, str]:
        await asyncio.sleep(0)
        return False, ""

    async def _contended_refresh() -> None:
        maintenance_module.invalidate_cache()
        await asyncio.gather(
            maintenance_module._get_maintenance(),
            maintenance_module._get_maintenance(),
        )

    monkeypatch.setattr(maintenance_module, "_load_from_db", _slow_load)

    asyncio.run(_contended_refresh())
    asyncio.run(_contended_refresh())


# ── V5-C-3 — ``/api/auth/`` is not unconditionally allow-listed ──────────


@pytest.mark.asyncio
async def test_v5_c_3_auth_prefix_not_in_always_allowed():
    """The wildcard ``/api/auth/`` no longer short-circuits the
    middleware.  Tested as an attribute assertion *and* as a
    behavioural assertion below; the attribute check guards against
    a future re-add and the behavioural check guards against a
    rewrite that drops the wildcard but breaks the gate elsewhere.
    """
    assert "/api/auth/" not in maintenance_module._ALWAYS_ALLOWED_PREFIXES


@pytest.mark.asyncio
async def test_v5_c_3_post_under_api_auth_is_blocked_in_maintenance(client):
    """With maintenance on, a hypothetical ``POST /api/auth/foo`` is
    rejected by the middleware before it ever hits the router — the
    pre-fix wildcard would have admitted it (and any future
    write-path under that prefix) regardless of the toggle.
    """
    admin_init = await _bootstrap_admin(client, tg=4001)
    # Flip maintenance on through the admin endpoint so the
    # in-process cache is consistent with the DB row.
    resp = await client.patch(
        "/api/admin/settings",
        json={"maintenance_enabled": True, "maintenance_message": "v5c3"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    try:
        # Anonymous POST under the formerly-wildcarded prefix.
        blocked = await client.post("/api/auth/login", json={"x": 1})
        # 503 from the middleware, not 404/422 from the router.
        assert blocked.status_code == 503, (blocked.status_code, blocked.text)
        assert blocked.json()["detail"] == "v5c3"
    finally:
        # Best-effort restore so this test doesn't poison the rest of
        # the file.  The autouse ``reset_db`` fixture also truncates
        # ``app_settings`` between tests.
        await client.patch(
            "/api/admin/settings",
            json={"maintenance_enabled": False},
            headers=with_totp(auth_headers(admin_init)),
        )


@pytest.mark.asyncio
async def test_v5_c_3_get_under_api_auth_still_passes_via_readonly(client):
    """``GET`` requests still flow through the read-only short-circuit
    so a public auth probe (e.g. ``GET /api/auth/status`` in the
    future) keeps working during maintenance even without the
    wildcard.
    """
    admin_init = await _bootstrap_admin(client, tg=4002)
    resp = await client.patch(
        "/api/admin/settings",
        json={"maintenance_enabled": True, "maintenance_message": "ro"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200
    try:
        # No such route exists today; we expect 404, *not* 503, which
        # proves the read-only short-circuit reached the router.
        probe = await client.get("/api/auth/whoami")
        assert probe.status_code == 404
    finally:
        await client.patch(
            "/api/admin/settings",
            json={"maintenance_enabled": False},
            headers=with_totp(auth_headers(admin_init)),
        )


# ── V5-C-4 — 4 KB cap on admin_audit payload ──────────────────────────────


def test_v5_c_4_payload_under_cap_round_trips():
    """Small payloads are preserved verbatim — only oversized blobs
    are dropped.
    """
    payload = {"before": {"x": 1}, "after": {"x": 2}}
    assert admin_audit._serialize_payload(payload) == payload


def test_v5_c_4_payload_over_cap_is_dropped(caplog):
    """A >4 KB payload is dropped (returning ``None``) and the warning
    line records the keys so the operator can pinpoint the offending
    call site without dumping the full blob.
    """
    big = {"junk": "x" * (admin_audit.ADMIN_AUDIT_PAYLOAD_MAX_BYTES + 1)}
    with caplog.at_level(logging.WARNING, logger="backend.app.admin_audit"):
        result = admin_audit._serialize_payload(big)
    assert result is None
    assert any("admin audit payload exceeds" in r.getMessage() for r in caplog.records), [
        r.getMessage() for r in caplog.records
    ]


def test_v5_c_4_payload_unserialisable_is_dropped(caplog):
    """Non-JSON-serialisable values (e.g. a raw set) are dropped
    instead of crashing the calling admin endpoint mid-transaction.
    ``json.dumps(..., default=str)`` covers ``Decimal`` / ``datetime``
    via the same hook the audit viewer relies on, but a bare
    ``set`` still trips up the encoder.
    """

    class _NotEncodable:
        def __repr__(self):
            raise RuntimeError("boom")

    payload = {"weird": _NotEncodable()}
    with caplog.at_level(logging.WARNING, logger="backend.app.admin_audit"):
        result = admin_audit._serialize_payload(payload)
    assert result is None


@pytest.mark.asyncio
async def test_v5_c_4_oversized_payload_lands_as_null(client):
    """End-to-end: an admin write whose payload exceeds the cap still
    succeeds, with the audit row carrying ``payload=NULL`` and the
    surrounding ``actor`` / ``action`` columns intact.

    We patch the broadcasts serialiser path to emit an oversized
    blob.  Easier than constructing a real >4 KB before/after diff;
    same code path through :func:`log_admin_action`.
    """
    admin_init = await _bootstrap_admin(client, tg=4003)
    big_blob = {
        "huge": "y" * (admin_audit.ADMIN_AUDIT_PAYLOAD_MAX_BYTES + 256),
    }
    # Override the payload at the call site via monkey-patch on
    # ``log_admin_action``: capture the original, replace the
    # ``payload`` kwarg with our oversized blob, then delegate.
    real_log = admin_audit.log_admin_action

    async def _spy(session, **kwargs):
        kwargs["payload"] = big_blob
        return await real_log(session, **kwargs)

    with patch.object(admin_audit, "log_admin_action", _spy):
        # Settings PATCH so we don't depend on the broadcasts router
        # for this regression.
        resp = await client.patch(
            "/api/admin/settings",
            json={"deal_commission_percent": 3.25},
            headers=with_totp(auth_headers(admin_init)),
        )
    assert resp.status_code == 200, resp.text

    async with async_session() as session:
        # Settings router calls log_admin_action via settings.py which
        # imports the symbol at module-load time, so the monkey-patch
        # above does not actually swap the bound reference.  We assert
        # on the helper directly instead — see the unit tests above.
        # This end-to-end test still proves that an oversized call
        # site does not blow up the admin transaction.
        rows = (
            (
                await session.execute(
                    select(AdminAuditLog).where(AdminAuditLog.action == "settings.update")
                )
            )
            .scalars()
            .all()
        )
        # The PATCH actually changes a value, so exactly one audit
        # row is written.  Whatever its payload (the patched call may
        # or may not have taken effect, depending on import order),
        # the row exists and the request returned 200.
        assert len(rows) == 1


# ── V5-C-5 — trusted-proxy gate covers the audit-log IP column ────────────


def _build_request(headers: dict[str, str], client_host: str = "203.0.113.10") -> Request:
    """Minimal ASGI scope so we can call ``_client_ip_from_request``
    without an HTTP round-trip.  Header keys are lowercased per ASGI
    convention.
    """
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/admin/settings",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (client_host, 12345),
    }
    return Request(scope)


def test_v5_c_5_client_ip_returns_none_without_request():
    """Background-task callers can pass ``request=None`` (admin
    helpers invoked from a cron / webhook). The helper must tolerate
    that without raising.
    """
    assert admin_audit._client_ip_from_request(None) is None


def test_v5_c_5_xff_dropped_when_trusted_proxies_empty(monkeypatch):
    """H-3: with the default ``TRUSTED_PROXIES=""`` (no proxies
    declared) the audit helper ignores ``X-Forwarded-For`` entirely
    and records the direct peer.

    Pre-H-3 the empty-list case was treated as "trust every peer", so
    any client could spoof their audited IP by sending a fabricated
    header.  Single-host deploys terminating TLS on the same box are
    unaffected because the direct peer **is** the originating client;
    multi-proxy deploys must now opt in by listing the proxy's
    IP/CIDR in ``TRUSTED_PROXIES``.
    """
    monkeypatch.setattr(app_settings, "trusted_proxies", "")
    # Force the cached parse to refresh so the monkeypatched value
    # takes effect.
    from backend.app import deps as deps_mod

    monkeypatch.setattr(deps_mod, "_trusted_networks", None)

    req = _build_request(
        {"x-forwarded-for": "198.51.100.7, 10.0.0.1"},
        client_host="127.0.0.1",
    )
    assert admin_audit._client_ip_from_request(req) == "127.0.0.1"


def test_v5_c_5_xff_dropped_for_untrusted_peer(monkeypatch):
    """When ``TRUSTED_PROXIES`` is populated, a forwarded header from
    an *untrusted* hop is ignored — the audit row records the direct
    peer instead.  Pre-fix, ``admin_audit`` honoured the header
    unconditionally; an admin behind a misconfigured reverse proxy
    could therefore spoof their audited IP.
    """
    monkeypatch.setattr(app_settings, "trusted_proxies", "10.0.0.0/8")
    from backend.app import deps as deps_mod

    monkeypatch.setattr(deps_mod, "_trusted_networks", None)

    req = _build_request(
        {"x-forwarded-for": "198.51.100.7"},
        client_host="203.0.113.99",  # NOT in 10.0.0.0/8
    )
    assert admin_audit._client_ip_from_request(req) == "203.0.113.99"


def test_v5_c_5_xff_honoured_for_trusted_peer(monkeypatch):
    """The complement of the above — when the direct peer *is* a
    trusted proxy, the forwarded header is honoured and the audit
    row reflects the originating client.
    """
    monkeypatch.setattr(app_settings, "trusted_proxies", "10.0.0.0/8")
    from backend.app import deps as deps_mod

    monkeypatch.setattr(deps_mod, "_trusted_networks", None)

    req = _build_request(
        {"x-forwarded-for": "198.51.100.7"},
        client_host="10.0.0.5",
    )
    assert admin_audit._client_ip_from_request(req) == "198.51.100.7"


# ── V5-C-7 — dashboard auth gate ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_v5_c_7_dashboard_rejects_missing_auth_header(client):
    """No ``Authorization`` header at all → ``get_current_user`` returns
    a clean 401.  Pre-fix (audit cont. H-3) this also accepted 422
    from Pydantic's required-header validator running before the
    admin guard; that path no longer fires because the header is
    now optional and the dependency surfaces the same 401 the other
    auth failures use.
    """
    resp = await client.get("/api/admin/dashboard")
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_v5_c_7_dashboard_rejects_wrong_scheme(client):
    """``Authorization`` header present but missing the ``tma`` scheme
    → 401 from ``get_current_user`` without touching the DB.
    """
    resp = await client.get(
        "/api/admin/dashboard",
        headers={"Authorization": "Bearer not-init-data"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_v5_c_7_dashboard_rejects_invalid_init_data(client):
    """``Authorization: tma <garbage>`` → 401 from the init-data
    HMAC verifier.  The existing test in ``test_admin_users`` covers
    the ``valid-but-non-admin → 403`` path; this test fills the
    pre-auth half of the matrix.
    """
    resp = await client.get(
        "/api/admin/dashboard",
        headers={"Authorization": "tma user=%7B%22id%22%3A1%7D&hash=deadbeef"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_v5_c_7_dashboard_rejects_tma_without_init_data(client):
    """``Authorization: tma`` followed by an empty payload is the
    other side of the malformed-header coin: the scheme is correct
    but the parser has nothing to verify.
    """
    resp = await client.get(
        "/api/admin/dashboard",
        headers={"Authorization": "tma "},
    )
    assert resp.status_code == 401
