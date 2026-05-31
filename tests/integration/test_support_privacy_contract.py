"""Privacy contract for ``/api/support`` endpoints (audit 4.4).

The ``user_id`` field on ``SupportPersonOut`` carries the Telegram
``tg_user_id`` of the admin/arbiter, NOT the internal database id —
asymmetric with the public ``UserPublicOut`` (V9 Comments 29/30)
which deliberately omits ``tg_user_id``.

This file documents the asymmetry as a regression test: if a future
maintainer decides to "harmonise" the public schemas by removing
``user_id`` from ``SupportPersonOut`` they will trip this test, at
which point the docstring on ``backend.app.routers.support`` should
be updated to reflect the new contract (or deleted alongside the
test).

The test also serves as living documentation: the ``id`` field is
the internal user id and ``user_id`` is ``tg_user_id`` — confusing,
but stable.
"""

from __future__ import annotations

from backend.app.db import async_session
from backend.app.models import User
from tests.helpers import auth_headers, signed_init_data


async def _make_user(
    client, *, tg_user_id: int, username: str, is_admin: bool = False, is_arbiter: bool = False
) -> int:
    """Bootstrap a user and optionally flag them admin / arbiter."""
    init = signed_init_data(tg_user_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    uid = resp.json()["id"]
    if is_admin or is_arbiter:
        async with async_session() as session:
            u = await session.get(User, uid)
            if is_admin:
                u.is_admin = True
            if is_arbiter:
                u.is_arbiter = True
            await session.commit()
    return uid


async def test_support_endpoints_expose_tg_user_id(client):
    """``/api/support/admins`` and ``/api/support/arbiters`` MUST
    include ``user_id`` set to the Telegram ``tg_user_id`` of each
    admin / arbiter.

    Documented privacy decision (4.4): the contract intentionally
    diverges from ``UserPublicOut``. See the docstring on
    ``backend.app.routers.support`` for the rationale.
    """
    # One admin (tg 30001) and one arbiter (tg 30002).
    admin_tg = 30001
    arbiter_tg = 30002
    admin_id = await _make_user(client, tg_user_id=admin_tg, username="adm_30001", is_admin=True)
    arbiter_id = await _make_user(
        client, tg_user_id=arbiter_tg, username="arb_30002", is_arbiter=True
    )

    # A regular caller (not admin / arbiter) — these endpoints just
    # require an authenticated user.
    caller_tg = 30003
    caller_init = signed_init_data(caller_tg, "caller_30003")
    # Bootstrap so the user row exists.
    await client.get("/api/me", headers=auth_headers(caller_init))

    # --- /admins ----------------------------------------------------
    resp = await client.get("/api/support/admins", headers=auth_headers(caller_init))
    assert resp.status_code == 200, resp.text
    admins = resp.json()
    assert isinstance(admins, list)
    rows = [r for r in admins if r.get("username") == "adm_30001"]
    assert len(rows) == 1, f"admin not surfaced: {admins}"
    row = rows[0]
    assert row["id"] == admin_id, "id field must carry the internal user id"
    assert row["user_id"] == admin_tg, (
        "4.4 contract: user_id MUST carry tg_user_id (audit privacy decision); "
        "if you intentionally changed this, update the docstring on "
        "backend.app.routers.support and delete this test."
    )
    assert row["prefix"] == "admin"
    assert row["admin"] == 1

    # --- /arbiters --------------------------------------------------
    resp = await client.get("/api/support/arbiters", headers=auth_headers(caller_init))
    assert resp.status_code == 200, resp.text
    arbiters = resp.json()
    rows = [r for r in arbiters if r.get("username") == "arb_30002"]
    assert len(rows) == 1, f"arbiter not surfaced: {arbiters}"
    row = rows[0]
    assert row["id"] == arbiter_id, "id field must carry the internal user id"
    assert row["user_id"] == arbiter_tg, (
        "4.4 contract: user_id MUST carry tg_user_id (audit privacy decision); "
        "if you intentionally changed this, update the docstring on "
        "backend.app.routers.support and delete this test."
    )
    assert row["prefix"] == "arbiter"


def test_is_cryptopay_configured_recognises_dev_placeholder(monkeypatch):
    """7.2 — the shared helper rejects the docker-compose default
    ``CRYPTOBOT_TOKEN`` placeholder and accepts a real-looking token.

    The five call-sites (``services_wallet.create_deposit_invoice``,
    ``routers/admin/system.status``, ``routers/admin/withdrawals``
    auto-mode, ``routers/admin/treasury.withdraw``, and
    ``services_wallet.create_withdrawal`` via the legacy alias) now
    funnel through ``is_cryptopay_configured`` so the heuristic is
    defined in one place. This test pins the heuristic so any future
    relaxation is explicit.
    """
    from backend.app.config import settings
    from backend.app.services_wallet import is_cryptopay_configured

    # Explicit-token form: the helper inspects ONLY the supplied token,
    # regardless of ``settings.cryptobot_token``.
    assert is_cryptopay_configured("") is False
    assert is_cryptopay_configured("000000:FAKE") is False
    assert is_cryptopay_configured("000123:REAL_LOOKING") is True
    assert is_cryptopay_configured("123456:AAEXAMPLEAAEXAMPLEAAEXAMPLE") is True
    assert is_cryptopay_configured("9999:abc") is True

    # No-arg form falls back to ``settings.cryptobot_token``. Patch
    # the setting through both placeholder and real-looking values and
    # confirm the helper picks them up correctly.
    monkeypatch.setattr(settings, "cryptobot_token", "")
    assert is_cryptopay_configured() is False

    monkeypatch.setattr(settings, "cryptobot_token", "000000:FAKE")
    assert is_cryptopay_configured() is False

    monkeypatch.setattr(settings, "cryptobot_token", "real-looking-token")
    assert is_cryptopay_configured() is True
