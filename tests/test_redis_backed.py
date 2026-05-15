"""P3.5 — Redis pub/sub and rate-limit coverage.

We don't require a live Redis to test the Redis paths: ``fakeredis`` is
a drop-in for ``redis.asyncio`` and is wired in via
:func:`backend.app.redis_client.override_for_tests`.

Each Redis-path test asserts:
* the in-memory fallback still triggers when no client is bound
  (sanity check that we didn't break the legacy behaviour);
* the Redis backend uses the right keys / counters.

The pub/sub test spins up the manager's listener task, publishes one
envelope via the same fakeredis instance, and verifies the local
delivery callback was invoked exactly once with the original payload.
"""

from __future__ import annotations

import asyncio
import json

import fakeredis.aioredis
import pytest
from fastapi import HTTPException

from backend.app import rate_limit, redis_client, ws


@pytest.fixture
async def fake_redis():
    """Provide a fresh fakeredis instance for the duration of the test."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_client.override_for_tests(client)
    try:
        yield client
    finally:
        await client.aclose()
        redis_client.override_for_tests(None)
        rate_limit.reset_state_for_tests()


# ── rate-limit Redis backend ─────────────────────────────────────────────


async def test_rate_limit_uses_redis_when_bound(fake_redis):
    """Each hit adds a ZSET entry; the (n+1)th raises 429."""
    # 3 hits under limit=3 must succeed.
    for _ in range(3):
        await rate_limit._hit("test-scope", "user:42", limit=3, window=60)

    # Sliding-window: one ZSET per ``(scope, principal)`` with one
    # entry per hit. The key no longer carries a bucket suffix.
    assert int(await fake_redis.zcard("rl:test-scope:user:42")) == 3

    # The 4th hit must raise 429 and must NOT be persisted (the Lua
    # script rejects before ``ZADD``).
    with pytest.raises(HTTPException) as exc:
        await rate_limit._hit("test-scope", "user:42", limit=3, window=60)
    assert exc.value.status_code == 429
    assert int(await fake_redis.zcard("rl:test-scope:user:42")) == 3


async def test_rate_limit_falls_back_to_inmemory_when_no_redis():
    """No Redis bound → uses the legacy in-process bucket."""
    # Explicit reset to make the test order-independent.
    redis_client.override_for_tests(None)
    rate_limit.reset_state_for_tests()

    for _ in range(2):
        await rate_limit._hit("inmemory-scope", "user:99", limit=2, window=60)
    with pytest.raises(HTTPException) as exc:
        await rate_limit._hit("inmemory-scope", "user:99", limit=2, window=60)
    assert exc.value.status_code == 429


async def test_rate_limit_redis_keys_are_per_principal(fake_redis):
    """Counters are isolated per (scope, principal) — one user can't lock another out."""
    await rate_limit._hit("isolation", "user:1", limit=1, window=60)
    # user:2 still gets their first hit even though user:1 already used theirs.
    await rate_limit._hit("isolation", "user:2", limit=1, window=60)
    with pytest.raises(HTTPException):
        await rate_limit._hit("isolation", "user:1", limit=1, window=60)


# ── WS pub/sub fan-out ───────────────────────────────────────────────────


async def test_ws_publish_uses_redis_when_bound(fake_redis):
    """``manager.publish`` PUBLISHes via Redis and the listener forwards
    the envelope to local sockets on this same instance."""
    mgr = ws.ConnectionManager()

    received: list[tuple[int, dict]] = []

    async def _capture(user_id: int, data):
        received.append((user_id, data))

    mgr._send_local = _capture  # type: ignore[method-assign]

    await mgr.start_subscriber()
    try:
        await mgr.publish(7777, {"event": "hello", "data": {"x": 1}})
        # Give the listener a moment to pick up the message.
        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0.02)
        assert received == [(7777, {"event": "hello", "data": {"x": 1}})]
    finally:
        await mgr.stop_subscriber()


async def test_ws_publish_falls_back_to_local_when_no_redis():
    """No Redis bound → ``publish`` calls ``_send_local`` synchronously."""
    redis_client.override_for_tests(None)
    mgr = ws.ConnectionManager()

    received: list[tuple[int, dict]] = []

    async def _capture(user_id: int, data):
        received.append((user_id, data))

    mgr._send_local = _capture  # type: ignore[method-assign]

    await mgr.publish(8888, {"event": "local-only", "data": {}})

    assert received == [(8888, {"event": "local-only", "data": {}})]
    # No subscriber task was spawned (we never called start_subscriber and
    # there's no Redis bound anyway).
    assert mgr._pubsub_task is None


async def test_ws_subscriber_is_idempotent(fake_redis):
    """Calling ``start_subscriber`` twice must not spawn two tasks."""
    mgr = ws.ConnectionManager()
    await mgr.start_subscriber()
    first_task = mgr._pubsub_task
    await mgr.start_subscriber()
    assert mgr._pubsub_task is first_task
    await mgr.stop_subscriber()


async def test_ws_publish_envelope_format(fake_redis):
    """The published JSON envelope carries ``user_id`` and ``data`` keys."""
    mgr = ws.ConnectionManager()

    # Subscribe directly so we can inspect what landed on the wire.
    ps = fake_redis.pubsub()
    await ps.subscribe(ws.WS_CHANNEL)

    await mgr.publish(123, {"event": "deal_message", "data": {"body": "hi"}})

    # Drain pubsub messages until we get the published one.
    envelope = None
    for _ in range(50):
        message = await ps.get_message(ignore_subscribe_messages=True, timeout=0.05)
        if message and message.get("type") == "message":
            envelope = json.loads(message["data"])
            break

    assert envelope == {"user_id": 123, "data": {"event": "deal_message", "data": {"body": "hi"}}}

    await ps.unsubscribe(ws.WS_CHANNEL)
    await ps.aclose()
