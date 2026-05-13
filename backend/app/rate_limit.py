"""Rate limiter for sensitive endpoints (P3.5: Redis-backed when configured).

A fixed-window counter keyed by ``(scope, principal)``:

* When ``settings.redis_url`` is set and Redis is reachable, counters
  live in Redis (``INCR`` + ``EXPIRE`` on a per-bucket key), so multiple
  uvicorn workers / replicas share the same limit.
* Otherwise we use the legacy in-process ``defaultdict`` (one window's
  worth of timestamps per key) — same behaviour we had before P3.5.

Both paths raise ``HTTPException(429)`` when the principal exceeds
``limit`` calls within ``window`` seconds.

Limits err on the generous side — the goal is griefer-protection
("100 rps from one user"), not business quotas (those belong in the
routers).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from .deps import CurrentUser
from .models import User
from .redis_client import get_redis

logger = logging.getLogger(__name__)

_buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
_lock = asyncio.Lock()


async def _hit_inmemory(scope: str, key: str, *, limit: int, window: float) -> None:
    now = time.monotonic()
    cutoff = now - window
    async with _lock:
        bucket = _buckets[(scope, key)]
        # Drop expired entries; bucket stays small even for hot keys
        # because we never store more than ``limit + 1`` items.
        if bucket and bucket[0] < cutoff:
            i = 0
            while i < len(bucket) and bucket[i] < cutoff:
                i += 1
            del bucket[:i]
        if len(bucket) >= limit:
            retry_after = max(0.0, bucket[0] + window - now)
            _raise_429(retry_after)
        bucket.append(now)


async def _hit_redis(scope: str, key: str, *, limit: int, window: float) -> None:
    """Fixed-window INCR/EXPIRE counter on Redis.

    The key embeds the bucket ordinal (``floor(epoch / window)``), so
    keys expire naturally once their window passes. We only set EXPIRE
    on the first INCR to avoid resetting TTL on every hit.
    """
    r = await get_redis()
    if r is None:
        await _hit_inmemory(scope, key, limit=limit, window=window)
        return
    try:
        bucket_id = int(time.time() // window)
        full_key = f"rl:{scope}:{key}:{bucket_id}"
        count = await r.incr(full_key)
        if count == 1:
            await r.expire(full_key, int(window) + 1)
        if count > limit:
            ttl = await r.ttl(full_key)
            retry_after = float(ttl) if ttl and ttl > 0 else window
            _raise_429(retry_after)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("rate-limit: redis hit failed; falling back to in-memory")
        await _hit_inmemory(scope, key, limit=limit, window=window)


async def _hit(scope: str, key: str, *, limit: int, window: float) -> None:
    """Record one hit, dispatching to Redis or the in-memory backend."""
    await _hit_redis(scope, key, limit=limit, window=window)


def _raise_429(retry_after: float) -> None:
    raise HTTPException(
        status_code=429,
        detail=(f"Слишком много запросов, попробуйте позже (через ~{int(retry_after) + 1} с)"),
        headers={"Retry-After": str(int(retry_after) + 1)},
    )


def _client_ip(request: Request) -> str:
    """Best-effort client IP. Honours X-Forwarded-For if set by the proxy."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client is None:
        return "unknown"
    return request.client.host or "unknown"


def rate_limit(scope: str, *, limit: int, window: float):
    """Create a FastAPI dependency enforcing ``limit`` calls per ``window`` s.

    Side-effect only — returns ``None`` so the dep can stack alongside
    the route's primary ``CurrentUser`` / ``PinUser`` dependency. Keys
    per authenticated ``User.id`` when initData is valid, falls back to
    the client IP otherwise.
    """

    async def _dep(request: Request, user: CurrentUser) -> None:
        await _hit(scope, f"user:{user.id}", limit=limit, window=window)

    return _dep


def rate_limit_anon(scope: str, *, limit: int, window: float):
    """Same as :func:`rate_limit` but keyed by IP only (no auth dep)."""

    async def _dep(request: Request) -> None:
        await _hit(scope, f"ip:{_client_ip(request)}", limit=limit, window=window)

    return _dep


def reset_state_for_tests() -> None:
    """Drop in-memory buckets — test fixtures call this between cases.

    The Redis backend isn't touched here because fakeredis fixtures
    rebuild a fresh instance per test anyway.
    """
    _buckets.clear()


# Pre-baked dependency aliases used by the routers. Tuning lives here so
# product-side limits aren't scattered across endpoint signatures.
RLPin = Annotated[None, Depends(rate_limit("pin", limit=5, window=60))]
RLMediaUpload = Annotated[None, Depends(rate_limit("media-upload", limit=20, window=60))]
RLDealCreate = Annotated[None, Depends(rate_limit("deal-create", limit=10, window=60))]
RLServiceCreate = Annotated[None, Depends(rate_limit("service-create", limit=10, window=60))]
RLWithdrawal = Annotated[None, Depends(rate_limit("withdrawal", limit=5, window=300))]
RLDealMessage = Annotated[None, Depends(rate_limit("deal-message", limit=30, window=60))]


__all__ = [
    "User",
    "rate_limit",
    "rate_limit_anon",
    "reset_state_for_tests",
    "RLPin",
    "RLMediaUpload",
    "RLDealCreate",
    "RLServiceCreate",
    "RLWithdrawal",
    "RLDealMessage",
]
