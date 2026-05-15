"""Rate-limit dependency tests.

Verifies the 429 response when the per-user bucket fills up and that
windows reset cleanly between cases. Each test resets the limiter via
the conftest fixture, so they don't interact.
"""

from __future__ import annotations

import io

from tests.helpers import auth_headers, setup_pin, signed_init_data


async def test_pin_rate_limit_blocks_after_threshold(client):
    """5 hits/min on the ``pin`` scope. ``setup_pin`` already consumes 1
    bucket slot via /api/pin/setup, so 4 wrong-PIN checks should still be
    honoured and the 5th must be rate-limited."""
    init = signed_init_data(3001, "rl_pin_user")
    # V5-A-4 (M) — ``9876`` is now in the blacklist; this test just
    # needs *some* strong PIN since /check below sends wrong PINs.
    await setup_pin(client, init, pin="5092")  # bucket: 1/5

    for i in range(4):  # bucket: 2..5 / 5
        resp = await client.post(
            "/api/pin/check",
            json={"pin": "0000"},
            headers=auth_headers(init),
        )
        assert resp.status_code != 429, f"hit {i} got 429: {resp.text}"

    blocked = await client.post(
        "/api/pin/check",
        json={"pin": "0000"},
        headers=auth_headers(init),
    )
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    assert int(blocked.headers["Retry-After"]) >= 1


async def test_media_upload_rate_limit(client):
    """20 hits/min on /api/media/upload — 21st should 429."""
    init = signed_init_data(3002, "rl_media_user")
    await setup_pin(client, init)

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

    for i in range(20):
        files = {"file": (f"a{i}.png", io.BytesIO(png), "image/png")}
        resp = await client.post(
            "/api/media/upload",
            data={"kind": "deal"},
            files=files,
            headers=auth_headers(init),
        )
        assert resp.status_code != 429, f"hit {i} got 429: {resp.text}"

    files = {"file": ("z.png", io.BytesIO(png), "image/png")}
    blocked = await client.post(
        "/api/media/upload",
        data={"kind": "deal"},
        files=files,
        headers=auth_headers(init),
    )
    assert blocked.status_code == 429


async def test_rate_limit_is_per_user(client):
    """User A spamming pin/check must NOT block user B."""
    a = signed_init_data(3101, "rl_a")
    b = signed_init_data(3102, "rl_b")
    # V5-A-4 (M) — the audit-blacklist rejects 1111/2222 at /setup;
    # use strong PINs that aren't on the leaked-PIN list.
    await setup_pin(client, a, pin="5837")
    await setup_pin(client, b, pin="4163")

    # Burn A's bucket — setup already used 1, so 4 more saturates it.
    for _ in range(4):
        await client.post("/api/pin/check", json={"pin": "0000"}, headers=auth_headers(a))
    blocked_a = await client.post("/api/pin/check", json={"pin": "0000"}, headers=auth_headers(a))
    assert blocked_a.status_code == 429

    # B is still fine.
    ok_b = await client.post("/api/pin/check", json={"pin": "4163"}, headers=auth_headers(b))
    assert ok_b.status_code == 200, ok_b.text


async def test_rate_limit_resets_between_tests(client):
    """If buckets weren't reset, this case would 429 immediately given the
    previous test already burned a bucket for the same scope.
    """
    init = signed_init_data(3001, "rl_pin_user")  # reused tg_user_id from earlier
    await setup_pin(client, init, pin="5092")
    resp = await client.post("/api/pin/check", json={"pin": "0000"}, headers=auth_headers(init))
    assert resp.status_code != 429


async def test_notifications_read_all_rate_limited_at_11(client):
    """V5-D-2 (M) — ``POST /api/notifications/read-all`` is a
    fan-out UPDATE that scans every unread row for the user.
    Without a throttle, a stolen Telegram initData could spam the
    endpoint and generate constant write churn on the
    ``notifications`` table. The ``RLMarkAllRead`` dep caps the
    endpoint at 10/min — the 11th call must 429.

    10/min is more than the UI ever does (a single tap per mailbox
    visit), so this won't bother any real client.
    """
    init = signed_init_data(3201, "rl_read_all_user")
    await setup_pin(client, init)

    statuses: list[int] = []
    for _ in range(10):
        resp = await client.post(
            "/api/notifications/read-all",
            headers=auth_headers(init),
        )
        statuses.append(resp.status_code)

    assert all(s == 200 for s in statuses), statuses

    blocked = await client.post(
        "/api/notifications/read-all",
        headers=auth_headers(init),
    )
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
