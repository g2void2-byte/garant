"""Lazy, optional Redis client (P3.5).

The app runs fine without Redis — WS broadcasts stay in-process and the
rate limiter uses a local dict. When ``settings.redis_url`` is set, the
first call to :func:`get_redis` connects and caches a single client.
Connection failure is non-fatal: the helper logs a warning and returns
``None`` so callers can fall back to their in-memory path.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .config import settings

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_client: Redis | None = None
_resolved: bool = False


async def get_redis() -> Redis | None:
    """Return a cached Redis client or ``None`` when unavailable.

    Safe to call from anywhere — the first hit performs a single ``PING``
    to validate connectivity. Subsequent hits return the cached client.

    If the initial connection failed we leave ``_resolved`` ``False`` so
    the next caller retries: a transient Redis outage at startup would
    otherwise wedge the process in "fall back to in-memory" mode
    forever and require a restart to recover.
    """
    global _client, _resolved
    if _resolved:
        return _client
    if not settings.redis_url:
        _resolved = True
        return None
    redacted_dsn = _redact_dsn(settings.redis_url)
    try:
        import redis.asyncio as aioredis

        c = aioredis.from_url(settings.redis_url, decode_responses=True)
        await c.ping()
        _client = c
        _resolved = True
        # V11-L-15 — structured-logging fields so the JSON-logger
        # downstream (Loki/Sentry) can pivot on event without
        # regexing the message body.
        logger.info(
            "redis: connected at %s",
            redacted_dsn,
            extra={"event": "redis.connect.ok", "redis_dsn": redacted_dsn},
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "redis: %s unreachable, falling back to in-process state",
            redacted_dsn,
            exc_info=True,
            extra={
                "event": "redis.connect.failed",
                "redis_dsn": redacted_dsn,
            },
        )
        _client = None
        # Deliberately do NOT set ``_resolved = True`` here so the next
        # call retries the connection.
    return _client


async def close_redis() -> None:
    """Close the cached client and reset the resolution flag."""
    global _client, _resolved
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:  # noqa: BLE001
            logger.exception(
                "redis: error closing client",
                extra={"event": "redis.close.failed"},
            )
    _client = None
    _resolved = False


def override_for_tests(client: Redis | None) -> None:
    """Inject a fakeredis client (or ``None``) without going through ``from_url``."""
    global _client, _resolved
    _client = client
    _resolved = True


def _redact_dsn(url: str) -> str:
    if "@" in url and "://" in url:
        head, _, rest = url.partition("://")
        creds, _, hostpart = rest.partition("@")
        if ":" in creds:
            user, _, _ = creds.partition(":")
            return f"{head}://{user}:***@{hostpart}"
    return url
