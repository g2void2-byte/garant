"""Rate limiter for sensitive endpoints.

A **sliding-window** counter keyed by ``(scope, principal)``:

* When ``settings.redis_url`` is set and Redis is reachable, counters
  live in Redis as a sorted set per key (one entry per hit, scored by
  the monotonic timestamp); a Lua script trims expired entries and
  increments atomically, so multiple uvicorn workers / replicas share
  the same limit.
* Otherwise we use the in-process ``deque`` of recent hit times —
  same effective behaviour, single-process scope.

Both paths raise ``HTTPException(429)`` when the principal exceeds
``limit`` calls within ``window`` seconds. Limits err on the generous
side — the goal is griefer-protection ("100 rps from one user"), not
business quotas (those belong in the routers).

Why sliding instead of fixed window (Comment 51 / H): a fixed window
keyed on ``floor(t / window)`` allows up to ``2 * limit`` calls in a
``window``-second span straddling a bucket boundary (e.g. ``limit``
hits at ``t = window - epsilon`` then another ``limit`` at
``t = window + epsilon``). For ``RLPin`` (``5/60s``) that is 10
attempts in ~100 ms which materially helps a PIN brute-force.

Why a Lua script (Comment 47 / H): the previous ``INCR`` + ``EXPIRE``
pair was two round-trips. If ``EXPIRE`` failed (network hiccup,
``MOVED`` redirect on Cluster, etc.) the key was left without a TTL
and blocked the principal forever. A Lua script is delivered as one
RESP command and is atomic per-shard, so TTL maintenance can't lag
behind ``ZADD``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from .deps import CurrentUser
from .models import User
from .redis_client import get_redis

logger = logging.getLogger(__name__)

# Sliding-window: per ``(scope, key)`` we keep the timestamps of the
# last ``limit`` hits. The deque is trimmed lazily on every call so a
# burst-then-quiet pattern doesn't grow memory linearly.
_buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_lock = asyncio.Lock()

# Sliding-window Lua script. Args:
#   KEYS[1] = full key (``rl:{scope}:{principal}``)
#   ARGV[1] = now (seconds, fractional)
#   ARGV[2] = window (seconds, fractional)
#   ARGV[3] = limit
# Behaviour:
#   * Removes all entries older than ``now - window`` (sliding eviction).
#   * Reads ``count`` of remaining entries.
#   * If ``count >= limit``, returns ``{0, retry_after_seconds}`` without
#     adding the current hit — caller raises 429.
#   * Otherwise ``ZADD`` the new hit (member is a unique-per-call
#     suffix so multiple hits in the same fractional second don't
#     collide), refreshes TTL, returns ``{1, 0}``.
# The TTL is reapplied every hit so an idle key still expires once
# the last hit ages out; it does NOT reset per-hit relative to a
# fixed bucket boundary.
_RL_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry = window
  if oldest[2] then
    retry = (tonumber(oldest[2]) + window) - now
    if retry < 0 then retry = 0 end
  end
  return {0, tostring(retry)}
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, math.ceil((window + 1) * 1000))
return {1, '0'}
"""

# Single cached Script handle per process; ``redis.asyncio`` resolves
# the SHA on first call and falls back to EVAL on NOSCRIPT.
_rl_script = None


async def _hit_inmemory(scope: str, key: str, *, limit: int, window: float) -> None:
    """Sliding-window counter in-process. Bounded by ``limit`` entries."""
    now = time.monotonic()
    cutoff = now - window
    async with _lock:
        bucket = _buckets[(scope, key)]
        # Pop expired entries from the left — single pass, O(k) where
        # k is the number of newly-expired hits.
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(0.0, bucket[0] + window - now)
            _raise_429(retry_after)
        bucket.append(now)


async def _hit_redis(scope: str, key: str, *, limit: int, window: float) -> None:
    """Sliding-window counter on Redis (atomic via Lua).

    Comment 47 (H) — the previous implementation issued ``INCR`` then
    ``EXPIRE`` as two separate calls. If ``EXPIRE`` failed for any
    reason the key had no TTL and stayed in Redis forever, denying
    the principal access until manual cleanup. A Lua script keeps the
    eviction + ZADD + EXPIRE atomic per shard.

    Comment 51 (H) — the fixed-window variant allowed ``2 * limit``
    calls right at a window boundary. Sliding-window (``ZREMRANGEBYSCORE``
    + ``ZCARD`` + ``ZADD``) tracks each hit's own timestamp, so the
    cap is honoured for any rolling ``window``-second slice.
    """
    global _rl_script
    r = await get_redis()
    if r is None:
        await _hit_inmemory(scope, key, limit=limit, window=window)
        return
    try:
        if _rl_script is None:
            _rl_script = r.register_script(_RL_LUA)
        full_key = f"rl:{scope}:{key}"
        now = time.time()
        # ZSET member must be unique per hit so two hits inside the
        # same fractional second do not collide and de-duplicate to
        # one entry. ``now`` + a per-process counter would also work;
        # ``time.time_ns`` is simpler and process-local uniqueness is
        # all we need because the Redis-side member set is per-key.
        member = f"{now:.6f}:{time.monotonic_ns()}"
        result = await _rl_script(
            keys=[full_key],
            args=[f"{now:.6f}", f"{window:.6f}", str(int(limit)), member],
        )
        # ``result`` decodes as ``[admitted, retry_after_str]``.
        admitted = int(result[0]) if isinstance(result, (list, tuple)) else 0
        if not admitted:
            try:
                retry_after = float(result[1])
            except (TypeError, ValueError, IndexError):
                retry_after = window
            _raise_429(retry_after)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        # V11-L-15 — structured-logging fields so the JSON-logger
        # downstream (Loki/Sentry) can pivot on event/scope without
        # regexing the message body. ``key`` is deliberately NOT in
        # ``extra`` — it would explode log cardinality (one timeseries
        # per user/IP) and ``scope`` already gives us the bucket.
        logger.exception(
            "rate-limit: redis hit failed; falling back to in-memory",
            extra={"event": "rate_limit.redis.failed", "scope": scope},
        )
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
    """Best-effort client IP. Delegates to ``deps._client_ip`` for
    consistent trusted-proxy handling, falling back to ``"unknown"``."""
    from .deps import _client_ip as _dep_client_ip

    return _dep_client_ip(request) or "unknown"


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
    rebuild a fresh instance per test anyway. The cached Lua script
    handle is also dropped so a re-created fakeredis fixture
    re-registers cleanly.
    """
    global _rl_script
    _buckets.clear()
    _rl_script = None


# Pre-baked dependency aliases used by the routers. Tuning lives here so
# product-side limits aren't scattered across endpoint signatures.
RLPin = Annotated[None, Depends(rate_limit("pin", limit=5, window=60))]
RLMediaUpload = Annotated[None, Depends(rate_limit("media-upload", limit=20, window=60))]
RLDealCreate = Annotated[None, Depends(rate_limit("deal-create", limit=10, window=60))]
RLServiceCreate = Annotated[None, Depends(rate_limit("service-create", limit=10, window=60))]
RLWithdrawal = Annotated[None, Depends(rate_limit("withdrawal", limit=5, window=300))]
RLDealMessage = Annotated[None, Depends(rate_limit("deal-message", limit=30, window=60))]
RLServiceComment = Annotated[None, Depends(rate_limit("service-comment", limit=10, window=60))]
# Admin endpoints get a generous limit — enough to never block normal
# usage (bulk actions, audit log pagination) but slow enough to flag a
# leaked/stolen admin session before the entire DB walks out the door.
RLAdmin = Annotated[None, Depends(rate_limit("admin", limit=600, window=60))]

# Browse-style reads (catalog of categories, reviews about a user, the
# support contact list). Limits are generous because these are normal
# navigation calls, but tight enough to refuse a scraper that wants
# every user's review log or the full admin/arbiter directory.
RLCategories = Annotated[None, Depends(rate_limit("categories", limit=120, window=60))]
RLReviewsList = Annotated[None, Depends(rate_limit("reviews-list", limit=60, window=60))]
RLSupport = Annotated[None, Depends(rate_limit("support", limit=60, window=60))]

# ``POST /api/notifications/read-all`` is a fan-out UPDATE
# that scans every unread row for the user. Without a throttle, an
# attacker with a stolen Telegram initData could spam the endpoint to
# generate constant write churn on the ``notifications`` table.
# 10/min is more than the UI ever does (a single tap per mailbox visit).
RLMarkAllRead = Annotated[None, Depends(rate_limit("mark-all-read", limit=10, window=60))]

# ``GET /api/wallet/deposits/{id}`` hits CryptoBot's
# ``get_invoices`` for every still-``pending`` deposit, then takes a
# ``SELECT ... FOR UPDATE`` on the row and possibly credits the
# balance. Pre-throttle a logged-in client could spin the endpoint at
# arbitrary rate per deposit_id — wasting our CryptoBot quota and
# producing constant lock-contention with the canonical webhook
# path. 2/30s per user is generous enough for the DepositPage's
# refresh-on-mount + a single user-initiated refresh, while pinning
# the upstream API rate to ≤4/min/user even under attack.
RLWalletPoll = Annotated[None, Depends(rate_limit("wallet-poll", limit=2, window=30))]

# V11-H-4 — ``POST /api/wallet/deposits`` is the *creation* side of
# the same CryptoBot integration. Unlike withdrawals it isn't
# PIN-gated (the legitimate user gets the money back anyway, so the
# PIN UX cost isn't worth the gain), but a hijacked initData could
# still burn the platform's CryptoBot quota by spamming invoice
# creation. 3/min/user covers the realistic UX (user opens the
# deposit page, mistypes the amount, retries) while pinning the
# upstream call rate to ≤3/min/user even under attack — well below
# any provider quota and tight enough that abuse is logged in our
# rate-limit counters before it can DoS the integration.
RLDeposit = Annotated[None, Depends(rate_limit("deposit", limit=3, window=60))]

# Audit L5 — ``POST /api/account/transfer/start`` issues a 6-digit
# transfer code and pushes a Telegram DM to the calling user. The
# endpoint sits behind the PIN gate but, post-PIN, the caller could
# spam it to generate noisy DMs (each call rotates the active code,
# so this is purely an annoyance — not a brute-force vector — but
# the DMs are still real notifications to a real Telegram chat).
# 5/min is generous for legitimate flows (the UI does a single start
# per attempt) and tight enough that an attacker who has captured a
# PIN session cannot fan out a flood of "🔁 Перенос аккаунта" DMs.
RLAccountTransferStart = Annotated[
    None, Depends(rate_limit("account-transfer-start", limit=5, window=60))
]


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
    "RLServiceComment",
    "RLAdmin",
    "RLCategories",
    "RLReviewsList",
    "RLSupport",
    "RLMarkAllRead",
    "RLWalletPoll",
    "RLDeposit",
    "RLAccountTransferStart",
]
