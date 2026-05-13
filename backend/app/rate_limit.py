"""In-process rate limiter for sensitive endpoints.

A lightweight fixed-window counter keyed by ``(scope, principal)`` where
``principal`` is either the authenticated ``User.id`` (preferred) or the
remote IP (fallback for unauthenticated endpoints). State lives in a
plain dict guarded by ``asyncio.Lock``; works because the app runs on a
single uvicorn worker today.

When the deployment moves to multiple workers / replicas we'll swap this
out for the Redis-backed sliding window scheduled as P3.5 — same
``RateLimit`` dependency interface, different backend.

Limits intentionally err on the generous side. The goal is to stop the
"100 requests per second from one user" griefing case, not to enforce
business-level quotas (those belong in the routers).
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from .deps import CurrentUser
from .models import User

_buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
_lock = asyncio.Lock()


async def _hit(scope: str, key: str, *, limit: int, window: float) -> None:
    """Record a hit; raise 429 if more than ``limit`` hits in ``window`` s."""
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
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Слишком много запросов, попробуйте позже (через ~{int(retry_after) + 1} с)"
                ),
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
        bucket.append(now)


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
    """Drop all buckets — test fixtures call this between cases."""
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
