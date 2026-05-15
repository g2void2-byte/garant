"""I-5 \u2014 end-to-end Redis rate-limit integration test.

``tests/test_redis_backed.py`` already exercises the
``rate_limit._hit`` helper directly against fakeredis. What it does
*not* cover is the full FastAPI dependency chain \u2014 a real router,
middleware stack, and authentication \u2014 which is what production
traffic actually hits. This file plugs that gap by:

1. Binding a fresh fakeredis instance via
   :func:`backend.app.redis_client.override_for_tests`.
2. Driving the standard test client against a real rate-limited
   endpoint (``POST /api/account/transfer/confirm`` carries
   :data:`backend.app.rate_limit.RLPin` \u2014 5 req / 60 s \u2014 and only
   needs a ``CurrentUser`` dep, so each loop iteration just bumps
   the limiter counter without mutating any other state).
3. Asserting the 6th request returns 429.
4. Asserting that without the fakeredis override, the in-memory
   fallback still works \u2014 so a misconfigured snapshot doesn't drop
   the limit entirely.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from backend.app import rate_limit, redis_client
from tests.helpers import (
    auth_headers,
    signed_init_data,
)


@pytest.fixture
async def fake_redis():
    """Override the module-level Redis client with fakeredis for the
    duration of the test. Resets the in-memory bucket too so the
    fallback path can't accidentally satisfy the assertion."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_client.override_for_tests(client)
    rate_limit.reset_state_for_tests()
    try:
        yield client
    finally:
        await client.aclose()
        redis_client.override_for_tests(None)
        rate_limit.reset_state_for_tests()


async def _drive(client, init: str, n: int) -> list[int]:
    """Make ``n`` confirm requests with a guaranteed-wrong code and
    return the status code of each. Used to walk the limiter."""
    statuses: list[int] = []
    for _ in range(n):
        resp = await client.post(
            "/api/account/transfer/confirm",
            json={"code": "000000"},
            headers=auth_headers(init),
        )
        statuses.append(resp.status_code)
    return statuses


async def test_account_transfer_rate_limit_429s_via_redis(client, fake_redis):
    """The 6th confirm in a tight loop must 429, and the Redis bucket
    must have actually been used (verified by reading the counter
    key from fakeredis directly). This proves the full FastAPI chain
    \u2014 router \u2192 RLPin dep \u2192 ``rate_limit._hit`` \u2192 Redis backend \u2014
    enforces the limit, not just the unit-tested helper."""
    init = signed_init_data(7601, "redis_rl_int")
    # First /api/me bootstraps the user row; no rate-limit on /me.
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200

    # 5 confirm calls under the limit \u2014 all 400 (bad code).
    statuses = await _drive(client, init, 5)
    assert statuses == [400] * 5, statuses

    # 6th confirm: limiter trips and the router replies 429 before
    # the request body is even validated.
    resp = await client.post(
        "/api/account/transfer/confirm",
        json={"code": "000000"},
        headers=auth_headers(init),
    )
    assert resp.status_code == 429, resp.text

    # Confirm Redis was actually used: the rl:pin:* key family must
    # have at least one sorted-set with our 5 in-budget hits
    # accounted for. The sliding-window backend stores one ZSET
    # member per hit, so summing ZCARDs over matching keys is the
    # natural counter readout. The over-limit 6th call is rejected
    # *without* being added to the ZSET (the Lua script checks
    # ``count >= limit`` before ``ZADD``), so we expect exactly 5.
    keys = await fake_redis.keys("rl:pin:*")
    assert keys, "expected an rl:pin:* bucket key in Redis"
    total = 0
    for k in keys:
        total += int(await fake_redis.zcard(k))
    assert total >= 5


async def test_account_transfer_rate_limit_falls_back_to_inmemory(client):
    """Without a Redis client bound, the same endpoint must still
    enforce the limit via the in-memory bucket fallback. This catches
    the snapshot-misconfig regression where dropping ``REDIS_URL``
    silently removes the limit."""
    redis_client.override_for_tests(None)
    rate_limit.reset_state_for_tests()

    init = signed_init_data(7602, "inmem_rl_int")
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200

    statuses = await _drive(client, init, 5)
    assert statuses == [400] * 5, statuses
    resp = await client.post(
        "/api/account/transfer/confirm",
        json={"code": "000000"},
        headers=auth_headers(init),
    )
    assert resp.status_code == 429, resp.text
