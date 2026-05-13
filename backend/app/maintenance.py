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
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from .db import async_session
from .models import AppSettings

logger = logging.getLogger(__name__)

_READONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Routes that *must* keep working during maintenance (read-only auth
# probes, the maintenance toggle itself, the WebSocket lifecycle, the
# bot webhook etc).
_ALWAYS_ALLOWED_PREFIXES = (
    "/api/admin/",
    "/api/auth/",
    "/api/settings/maintenance",
    "/health",
    "/assets/",
    "/media/",
)


async def maintenance_middleware(request: Request, call_next: Callable[[Request], Awaitable]):
    """Block state-changing calls when maintenance mode is on."""
    method = request.method.upper()
    path = request.url.path

    # Fast-path: read-only or allow-listed paths bypass the DB lookup.
    if method in _READONLY_METHODS:
        return await call_next(request)
    if any(path.startswith(prefix) for prefix in _ALWAYS_ALLOWED_PREFIXES):
        return await call_next(request)

    # One quick singleton lookup. The AppSettings row is created by the
    # seed script; the middleware no-ops if it's missing for any reason.
    try:
        async with async_session() as session:
            row = (
                await session.execute(select(AppSettings).order_by(AppSettings.id).limit(1))
            ).scalar_one_or_none()
    except Exception:
        logger.exception("maintenance middleware: settings lookup failed")
        return await call_next(request)

    if row is None or not row.maintenance_enabled:
        return await call_next(request)

    # Admin /api/admin/* paths are in _ALWAYS_ALLOWED_PREFIXES so admins
    # always have a way to flip the switch back. For every other write,
    # respond 503 with the configured message.
    return JSONResponse(
        status_code=503,
        content={"detail": row.maintenance_message or "Сервис на технических работах."},
        headers={"Retry-After": "60"},
    )
