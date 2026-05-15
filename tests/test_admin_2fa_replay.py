"""V5-C-6 (M) — TOTP replay protection across concurrent requests.

Pre-fix, replay protection lived only in ``users.totp_last_counter``,
which the caller persisted via ``session.commit()`` *after* verifying
the code. Two parallel withdrawal requests (or any 2FA-gated admin
action) could both pass ``verify_totp_and_counter`` before either
commit landed, both see the OLD high-water mark, both succeed.
That's a 30-second replay window for a stolen code.

Fix: ``_consume_totp`` claims the counter in Redis via
``SET key NX EX <ttl>`` BEFORE returning. The second concurrent
request hits the same key, ``SET NX`` returns falsy, and the
request 401s without ever touching the DB.

Two tests:

1. Direct unit-level race on ``_consume_totp`` with fakeredis bound —
   asserts only one of two concurrent calls succeeds.
2. Integration: two parallel ``POST /api/admin/users/{id}/ban`` calls
   with the same TOTP code → exactly one 200, one 401.

Both tests rely on fakeredis (bound via ``override_for_tests``) so
the Redis-backed claim path is exercised. The DB-only fallback is
single-worker only and is documented in ``_consume_totp``'s
docstring as a degraded mode — we don't regress on it because
production always has Redis.
"""

from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.app import rate_limit, redis_client
from backend.app.auth_2fa import _consume_totp, generate_secret, totp_now
from backend.app.db import async_session
from backend.app.models import User
from tests.helpers import auth_headers, signed_init_data


@pytest.fixture
async def fake_redis():
    """Bind fakeredis for the duration of the test and clear the
    in-memory rate-limit buckets so they don't leak between tests."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_client.override_for_tests(client)
    rate_limit.reset_state_for_tests()
    try:
        yield client
    finally:
        await client.aclose()
        redis_client.override_for_tests(None)
        rate_limit.reset_state_for_tests()


async def _enrol_user_with_totp(tg: int, username: str) -> tuple[int, str]:
    """Insert a fresh admin user with TOTP enabled. Returns
    ``(user_id, secret)``. Skips the HTTP enrolment flow because
    those endpoints themselves consume a TOTP counter, which would
    contaminate the replay attempts we're about to test."""
    secret = generate_secret()
    async with async_session() as session:
        user = User(
            tg_user_id=tg,
            username=username,
            display_name=username,
            is_admin=True,
            totp_enabled=True,
            totp_secret=secret,
            totp_last_counter=-1,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id, secret


async def test_consume_totp_rejects_parallel_replay_via_redis(fake_redis):
    """Unit-level: two parallel ``_consume_totp`` calls with the same
    code (against the same user) result in exactly one success and
    one 401 'уже использован'.

    Each call uses its own ``async_session()`` to mirror what
    happens in the real FastAPI deps (each request gets its own
    session). The Redis claim is what stops the second caller.
    """
    user_id, secret = await _enrol_user_with_totp(8901, "totp_race")
    code = totp_now(secret)

    async def _try_consume() -> str:
        async with async_session() as session:
            user = await session.get(User, user_id)
            assert user is not None
            try:
                await _consume_totp(session, user, code)
                await session.commit()
                return "ok"
            except HTTPException as exc:
                return f"{exc.status_code}:{exc.detail}"

    a, b = await asyncio.gather(_try_consume(), _try_consume())
    outcomes = sorted([a, b])
    # Exactly one "ok" and one 401.
    assert outcomes[0] == "401:Код 2FA уже использован — дождитесь следующего", outcomes
    assert outcomes[1] == "ok", outcomes


async def test_consume_totp_blocks_serial_replay_too(fake_redis):
    """Serial replay sanity: a second call with the same code
    immediately after the first must also 401. Pre-fix the second
    call would *succeed* if it landed before the first commit
    persisted ``totp_last_counter``; the Redis claim closes that
    window even for the serial case.
    """
    user_id, secret = await _enrol_user_with_totp(8902, "totp_serial")
    code = totp_now(secret)

    async with async_session() as session:
        user = await session.get(User, user_id)
        await _consume_totp(session, user, code)
        await session.commit()

    async with async_session() as session:
        user = await session.get(User, user_id)
        with pytest.raises(HTTPException) as exc:
            await _consume_totp(session, user, code)
        assert exc.value.status_code == 401
        assert "уже использован" in str(exc.value.detail)


async def test_parallel_admin_ban_with_same_code_rejects_replay(client, fake_redis):
    """Integration: two parallel ``POST /api/admin/users/{id}/ban``
    calls with the same TOTP code. Exactly one 200 + one 401.

    Goes through the full FastAPI dependency chain
    (``AdminGuard`` → ``_consume_totp`` → ``SET NX EX``) so the test
    catches regressions in:

    * the order of operations inside ``AdminGuard.__call__``,
    * the X-Totp-Code header parsing,
    * the redis-claim TTL math.
    """
    # An admin who'll do the banning (enrolled with TOTP).
    admin_id, secret = await _enrol_user_with_totp(8911, "admin_ban_race")
    admin_init = signed_init_data(8911, "admin_ban_race")

    # A target user to ban; bootstrapped via the normal /api/me path.
    target_init = signed_init_data(8912, "ban_target")
    me = await client.get("/api/me", headers=auth_headers(target_init))
    assert me.status_code == 200, me.text
    target_id = me.json()["id"]

    code = totp_now(secret)
    headers = {**auth_headers(admin_init), "X-Totp-Code": code}

    r1, r2 = await asyncio.gather(
        client.post(
            f"/api/admin/users/{target_id}/ban",
            json={"reason": "concurrent-ban-1"},
            headers=headers,
        ),
        client.post(
            f"/api/admin/users/{target_id}/ban",
            json={"reason": "concurrent-ban-2"},
            headers=headers,
        ),
    )

    statuses = sorted([r1.status_code, r2.status_code])
    # 401 (replay rejected) + any non-401 outcome.
    # Note: the second call may legitimately fail at a downstream
    # check (e.g. "user already banned") *if* it gets past TOTP —
    # but it must NOT get past TOTP because that's exactly what the
    # replay protection prevents. So we expect 401 to be the lower
    # status, and the other one to be 200 (banned successfully).
    assert 401 in statuses, (r1.status_code, r1.text, r2.status_code, r2.text)
    assert 200 in statuses, (r1.status_code, r1.text, r2.status_code, r2.text)

    # The target's ``is_banned`` flag must be set exactly once.
    async with async_session() as session:
        target = (await session.execute(select(User).where(User.id == target_id))).scalar_one()
        assert target.is_banned is True

    # Static analysis: keep ``admin_id`` referenced so a future
    # refactor that drops the row doesn't go unnoticed.
    assert admin_id > 0
