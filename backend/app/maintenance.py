"""Global maintenance switch.

When ``app_settings.maintenance_enabled`` is ``True`` the API responds
503 with the configured message for *every* state-changing request,
except those issued by an admin (``user.is_admin=true``).

Read-only requests (``GET``, ``HEAD``, ``OPTIONS``) still pass through
so users can see the existing UI rendered with the maintenance banner
overlay — but every write endpoint, including those on the bot, is
blocked.

Implemented as a FastAPI middleware so it sits in front of route
dependencies and short-circuits before any expensive work.

The middleware caches the flag in-process with a short TTL so a busy
endpoint doesn't open a fresh DB session per write. The cache is
invalidated explicitly by the admin settings PATCH handler so toggling
the flag takes effect immediately for the admin who flipped it;
peer-instance staleness is bounded by ``_TTL_SECONDS`` (other workers
catch up within at most that window).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from .config import settings
from .db import async_session
from .models import AppSettings

logger = logging.getLogger(__name__)

_READONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Routes that *must* keep working during maintenance (read-only auth
# probes, the maintenance toggle itself, the WebSocket lifecycle, the
# bot webhook etc).
#
# ``/api/payments/webhook/`` belongs here too: CryptoBot retries on
# non-2xx with exponential backoff and after enough failures drops the
# update entirely, which would silently lose deposit credits across
# the maintenance window.
#
# V5-C-3 — ``/api/auth/`` is intentionally *not* in this list.  No
# routes mount under that prefix today, and read-only auth probes
# (``GET /api/auth/...``) would be admitted by the ``_READONLY_METHODS``
# short-circuit anyway.  Carrying the wildcard would silently allow
# any future ``POST /api/auth/login`` to keep writing user/session
# rows during maintenance — exactly the failure mode the switch is
# meant to prevent.  If a future write-path under ``/api/auth/`` truly
# needs to bypass maintenance (e.g. an admin-recovery flow), add the
# specific endpoint here rather than re-broadening the prefix.
_ALWAYS_ALLOWED_PREFIXES = (
    "/api/admin/",
    "/api/payments/webhook/",
    "/api/settings/maintenance",
    "/health",
    "/assets/",
    "/media/",
)


# ── In-process cache ───────────────────────────────────
#
# The cache stores ``(expires_at, enabled, message)``. ``expires_at``
# is the monotonic ``time.monotonic()`` deadline after which the entry
# is considered stale and the next call refreshes from the DB. The
# admin "settings.update" handler calls :func:`invalidate_cache` after
# committing, so a toggle is reflected on the same process immediately;
# peers refresh within ``_TTL_SECONDS``.
#
# V5-C-2 — 5 s is short enough that a peer worker on a multi-instance
# deploy reflects an admin toggle within the same screen refresh,
# without measurably increasing DB load (the row is one indexed SELECT
# off a 1-row table, ~0.2 ms even on a cold cache).  Pre-fix this was
# 30 s, which meant other workers could serve writes for half a minute
# after maintenance had been turned on.

_TTL_SECONDS = 5.0

# V5-C-1 — throttle the "DB lookup failed" log line.  Pre-fix every
# request during a DB outage emitted a fresh ``logger.exception`` (the
# error-path cache TTL was 1 s, so we re-tried — and re-logged — every
# second on every middleware path).  At even modest traffic this
# floods stderr / Sentry with the same traceback and drowns out the
# actual signal.  We now keep a monotonic deadline and only emit the
# traceback once per ``_DB_ERROR_LOG_INTERVAL_SECONDS``; the suppressed
# count is included in the next log so observability is preserved.
_DB_ERROR_LOG_INTERVAL_SECONDS = 60.0

_db_error_log_state: dict[str, float | int] = {"next_emit_at": 0.0, "suppressed": 0}

_cache: tuple[float, bool, str] | None = None
_cache_lock = asyncio.Lock()


def invalidate_cache() -> None:
    """Drop the cached maintenance flag.

    Called by the admin settings PATCH handler after committing a
    change so the next request on the same worker re-reads the row
    instead of waiting up to ``_TTL_SECONDS`` for the TTL to expire.
    """
    global _cache
    _cache = None


def _reset_db_error_log_state() -> None:
    """Reset the throttled-log state.  Test-only hook."""
    _db_error_log_state["next_emit_at"] = 0.0
    _db_error_log_state["suppressed"] = 0


def _log_db_lookup_failure() -> None:
    """Emit the DB-lookup-failed traceback at most once per
    :data:`_DB_ERROR_LOG_INTERVAL_SECONDS`.

    Calls that fall inside the window increment a ``suppressed``
    counter; when the next call escapes the window it carries the
    suppressed count so we don't lose visibility into how many
    failures happened during the silent stretch.
    """
    now = time.monotonic()
    next_emit_at = _db_error_log_state["next_emit_at"]
    suppressed = int(_db_error_log_state["suppressed"])
    if now >= next_emit_at:
        if suppressed:
            logger.exception(
                "maintenance middleware: settings lookup failed "
                "(suppressed %d similar failures in the last %.0fs)",
                suppressed,
                _DB_ERROR_LOG_INTERVAL_SECONDS,
            )
        else:
            logger.exception("maintenance middleware: settings lookup failed")
        _db_error_log_state["next_emit_at"] = now + _DB_ERROR_LOG_INTERVAL_SECONDS
        _db_error_log_state["suppressed"] = 0
    else:
        _db_error_log_state["suppressed"] = suppressed + 1


async def _load_from_db() -> tuple[bool, str]:
    """Fetch the maintenance flag + message directly. No caching."""
    async with async_session() as session:
        row = (
            await session.execute(select(AppSettings).order_by(AppSettings.id).limit(1))
        ).scalar_one_or_none()
    if row is None:
        return False, ""
    return bool(row.maintenance_enabled), row.maintenance_message or ""


async def _get_maintenance() -> tuple[bool, str]:
    """Return ``(enabled, message)`` from cache or DB.

    Wraps the refresh in an ``asyncio.Lock`` so a thundering herd of
    concurrent writes during cold-cache doesn't open ``N`` sessions in
    parallel.
    """
    global _cache
    now = time.monotonic()
    cached = _cache
    if cached is not None and cached[0] > now:
        return cached[1], cached[2]
    async with _cache_lock:
        cached = _cache
        if cached is not None and cached[0] > time.monotonic():
            return cached[1], cached[2]
        try:
            enabled, message = await _load_from_db()
        except Exception:
            _log_db_lookup_failure()
            # Default policy is fail-open: don't block writes if the
            # DB is down. ``settings.maintenance_fail_closed=true``
            # flips this to fail-closed for stricter deploys — see
            # the doc comment on the config field. Either way the
            # entry is cached briefly so we don't hammer a failing
            # DB; pick a short TTL on error so recovery is quick.
            if settings.maintenance_fail_closed:
                fallback_msg = "Сервис временно недоступен (проверка статуса не удалась)."
                _cache = (time.monotonic() + 1.0, True, fallback_msg)
                return True, fallback_msg
            _cache = (time.monotonic() + 1.0, False, "")
            return False, ""
        _cache = (time.monotonic() + _TTL_SECONDS, enabled, message)
        return enabled, message


async def maintenance_middleware(request: Request, call_next: Callable[[Request], Awaitable]):
    """Block state-changing calls when maintenance mode is on."""
    method = request.method.upper()
    path = request.url.path

    # Fast-path: read-only or allow-listed paths bypass even the cache
    # lookup.
    if method in _READONLY_METHODS:
        return await call_next(request)
    if any(path.startswith(prefix) for prefix in _ALWAYS_ALLOWED_PREFIXES):
        return await call_next(request)

    enabled, message = await _get_maintenance()
    if not enabled:
        return await call_next(request)

    # Admin /api/admin/* paths are in _ALWAYS_ALLOWED_PREFIXES so admins
    # always have a way to flip the switch back. For every other write,
    # respond 503 with the configured message.
    return JSONResponse(
        status_code=503,
        content={"detail": message or "Сервис на технических работах."},
        headers={"Retry-After": "60"},
    )
