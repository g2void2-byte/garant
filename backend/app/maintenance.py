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
_ALWAYS_ALLOWED_PREFIXES = (
    "/api/admin/",
    "/api/auth/",
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

_TTL_SECONDS = 30.0

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
            logger.exception("maintenance middleware: settings lookup failed")
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
