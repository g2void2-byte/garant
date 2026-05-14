"""I-4 \u2014 dedicated DoS coverage for the account-transfer confirm
endpoint.

The audit flagged that we had no test exercising the *lockout* side
of the brute-force defence end-to-end: ``RLPin`` caps confirm calls
at 5 / minute per caller, and after the N+1th attempt the limiter
should return 429 even when the next request carries the *correct*
code. This file complements the lighter-weight rate-limit smoke in
``test_security_audit.py`` by walking the limiter all the way to its
lockout state, then verifying the real code is rejected during the
lock window, and finally verifying the counter resets so the user
can recover.
"""

from __future__ import annotations

from sqlalchemy import select

from tests.helpers import (
    auth_headers,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)


async def _issue_transfer_code(client, source_init: str, tg_user_id: int) -> str:
    """Same helper shape as in ``test_security_audit.py`` \u2014 issue a
    code via the service layer so we can read the plaintext (the HTTP
    endpoint only sends it through the bot)."""
    from backend.app.db import async_session
    from backend.app.models import User
    from backend.app.services_account import issue_code

    await setup_pin(client, source_init)
    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, tg_user_id)
        source = await session.get(User, user_id)
        assert source is not None
        code, _ = await issue_code(session, source)
    return code


async def test_transfer_confirm_lockout_rejects_correct_code(client):
    """Walk the limiter to its 429 state and verify that, while
    locked, even the *correct* code is refused at the rate-limit
    layer. This is the DoS scenario flagged in I-4: an attacker can
    deliberately burn the legitimate user's request budget before the
    user submits their own code, locking them out.

    After ``reset_state_for_tests`` clears the limiter (mirroring the
    natural window expiry), the same correct code is accepted \u2014 so
    the lockout is bounded.
    """
    from backend.app.db import async_session
    from backend.app.models import AccountTransferCode
    from backend.app.rate_limit import reset_state_for_tests

    reset_state_for_tests()

    source_init = signed_init_data(9301, "src9301")
    real_code = await _issue_transfer_code(client, source_init, 9301)

    target_init = signed_init_data(9302, "tgt9302")
    resp = await client.get("/api/me", headers=auth_headers(target_init))
    assert resp.status_code == 200

    # RLPin allows 5 requests / 60 s. Burn all 5 on wrong codes from
    # the attacker (= same caller as the legitimate one, worst case).
    statuses: list[int] = []
    for i in range(5):
        wrong = f"{(int(real_code) + i + 1) % 1_000_000:06d}"
        if wrong == real_code:
            wrong = "000000" if real_code != "000000" else "111111"
        resp = await client.post(
            "/api/account/transfer/confirm",
            json={"code": wrong},
            headers=auth_headers(target_init),
        )
        statuses.append(resp.status_code)
    # All 5 must have hit the application (bad code \u2192 400), not the
    # limiter yet \u2014 if they 429'd before exhausting the budget, the
    # limit got reduced and the test is no longer meaningful.
    assert statuses == [400] * 5, statuses

    # The 6th confirm \u2014 even with the REAL code \u2014 must 429 because
    # the limiter is now exhausted. This is the lockout the audit
    # asks us to assert.
    resp = await client.post(
        "/api/account/transfer/confirm",
        json={"code": real_code},
        headers=auth_headers(target_init),
    )
    assert resp.status_code == 429, resp.text

    # The legitimate code itself was not consumed: per-code attempts
    # stay at 0 because ``_register_miss`` is a no-op (H-4 fix). So
    # once the limiter window passes \u2014 simulated here by calling
    # ``reset_state_for_tests`` \u2014 the user can recover with the same
    # code they originally received.
    async with async_session() as session:
        row = (await session.execute(select(AccountTransferCode))).scalar_one()
        assert row.consumed_at is None
        assert row.attempts == 0

    reset_state_for_tests()
    resp = await client.post(
        "/api/account/transfer/confirm",
        json={"code": real_code},
        headers=auth_headers(target_init),
    )
    # Source row's tg_user_id got reassigned to target's \u2014 the
    # endpoint replies with the source's NEW tg_user_id, which equals
    # the target's tg id.
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["tg_user_id"] == 9302


async def test_transfer_confirm_lockout_window_is_per_caller(client):
    """A separate caller (different ``signed_init_data`` \u2192 different
    user-keyed bucket) must not inherit a previous caller's lockout
    state. This protects against an attacker preemptively burning
    everyone's quota."""
    from backend.app.rate_limit import reset_state_for_tests

    reset_state_for_tests()

    init_a = signed_init_data(9401, "caller_a")
    resp = await client.get("/api/me", headers=auth_headers(init_a))
    assert resp.status_code == 200

    # Burn caller_a's budget with wrong codes.
    for _ in range(5):
        await client.post(
            "/api/account/transfer/confirm",
            json={"code": "000000"},
            headers=auth_headers(init_a),
        )
    # caller_a is now locked.
    resp = await client.post(
        "/api/account/transfer/confirm",
        json={"code": "000000"},
        headers=auth_headers(init_a),
    )
    assert resp.status_code == 429

    # caller_b's first request lands on a fresh bucket.
    init_b = signed_init_data(9402, "caller_b")
    resp = await client.get("/api/me", headers=auth_headers(init_b))
    assert resp.status_code == 200
    resp = await client.post(
        "/api/account/transfer/confirm",
        json={"code": "000000"},
        headers=auth_headers(init_b),
    )
    # 400 (bad code) or 200 (correct against a code we didn't seed:
    # impossible, so 400); the key is it must NOT be 429.
    assert resp.status_code != 429, resp.text
