"""Items 12 / 13 / 15 / 16 — admin-write → user-read consistency.

The pre-fix bug was that admin mutations on a target user landed in
fields the user-facing serializer never read:

* ``POST /api/admin/users/:id/stats`` used to write ``deposit_total``,
  but the public profile reads ``trust_deposit_balance`` for its
  ``deposit`` field. The lifetime aggregate has since been removed
  outright — the only path that mutates the user-visible deposit is
  now ``POST /api/admin/users/:id/trust-deposit``.
* The admin-only ``POST /api/admin/wallets/:id/adjust`` *does* write
  the right column, but the user has no surface in the *profile* that
  shows fiat balances, so the change was invisible to the user.
* ``GET /api/wallet/balances`` and ``GET /api/wallet/currencies`` used
  to return every active currency; the user-facing pages now filter
  to ``kind=fiat`` so crypto rows never reach the dropdown.

This module sweeps the three flows end-to-end:

1. Admin ``trust-deposit`` endpoint → ``GET /api/me.deposit``.
2. Admin ``wallets/<id>/adjust`` → ``GET /api/wallet/balances`` for
   the target user.
3. ``GET /api/wallet/{balances,currencies}?kind=fiat`` returns only
   fiat rows.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import AdminAuditLog, User
from tests.helpers import auth_headers, signed_init_data, with_totp


async def _bootstrap(client, *, tg_user_id: int, username: str) -> int:
    init = signed_init_data(tg_user_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _promote_admin(uid: int) -> None:
    async with async_session() as session:
        u = await session.get(User, uid)
        assert u is not None
        u.is_admin = True
        await session.commit()


# ── Item 12 — admin sets trust deposit, user sees ``deposit`` ───────────────


async def test_admin_trust_deposit_propagates_to_user_deposit(client):
    """``POST /api/admin/users/:id/trust-deposit`` writes
    ``trust_deposit_balance``, which the public ``UserOut`` /
    ``UserPublicOut`` surface as ``deposit``. Pre-fix the legacy
    ``set_stats`` endpoint wrote ``deposit_total`` instead (since
    removed), which never reached the user-side serializer.
    """
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _promote_admin(admin_id)

    target_init = signed_init_data(2, "bob")
    target_id = await _bootstrap(client, tg_user_id=2, username="bob")

    # Admin sets the new value.
    resp = await client.post(
        f"/api/admin/users/{target_id}/trust-deposit",
        json={"amount": "100"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["trust_deposit_balance"] == pytest.approx(100.0)

    # Target user reads ``GET /api/me`` — public ``deposit`` reflects the change.
    me = await client.get("/api/me", headers=auth_headers(target_init))
    assert me.status_code == 200, me.text
    assert me.json()["deposit"] == pytest.approx(100.0)


async def test_admin_trust_deposit_audit_row(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _promote_admin(admin_id)
    target_id = await _bootstrap(client, tg_user_id=2, username="bob")

    resp = await client.post(
        f"/api/admin/users/{target_id}/trust-deposit",
        json={"amount": "42.5", "reason": "test"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200

    async with async_session() as session:
        audits = (
            (
                await session.execute(
                    select(AdminAuditLog).where(AdminAuditLog.action == "user.set_trust_deposit")
                )
            )
            .scalars()
            .all()
        )
        assert len(audits) == 1
        assert audits[0].target_id == target_id
        assert audits[0].reason == "test"


async def test_admin_trust_deposit_rejects_negative(client):
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _promote_admin(admin_id)
    target_id = await _bootstrap(client, tg_user_id=2, username="bob")

    resp = await client.post(
        f"/api/admin/users/{target_id}/trust-deposit",
        json={"amount": -10},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 422


async def test_admin_user_detail_exposes_trust_deposit(client):
    """``AdminUserDetailOut`` surfaces ``trust_deposit_balance`` — the
    single column the public profile reads as ``deposit``. The
    legacy ``deposit_total`` aggregate was removed in the same patch
    that dropped the column.
    """
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _promote_admin(admin_id)
    target_id = await _bootstrap(client, tg_user_id=2, username="bob")

    async with async_session() as session:
        u = await session.get(User, target_id)
        assert u is not None
        u.trust_deposit_balance = Decimal("100")
        await session.commit()

    resp = await client.get(f"/api/admin/users/{target_id}", headers=auth_headers(admin_init))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "deposit_total" not in body
    assert body["trust_deposit_balance"] == pytest.approx(100.0)


# ── Item 13 — admin wallet adjust visible in user's /wallet/balances ────────


async def test_admin_wallet_adjust_visible_in_user_balances(client):
    """``POST /api/admin/wallets/<uid>/adjust`` increments
    ``UserBalance.amount`` for the given currency; the target user's
    ``GET /api/wallet/balances`` reflects that change immediately.

    Pre-fix the admin endpoint worked but no user-facing surface
    rendered fiat balances anywhere except the wallet page, so the
    bug report read as "admin says it applied, user sees nothing" —
    even though the database was updated correctly. This test pins
    the contract end-to-end so a regression in either layer breaks
    here.
    """
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _promote_admin(admin_id)

    target_init = signed_init_data(2, "bob")
    target_id = await _bootstrap(client, tg_user_id=2, username="bob")

    resp = await client.post(
        f"/api/admin/wallets/{target_id}/adjust",
        json={"currency_code": "USD", "amount": 75.25, "reason": "manual top-up"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text

    balances = await client.get("/api/wallet/balances?kind=fiat", headers=auth_headers(target_init))
    assert balances.status_code == 200, balances.text
    by_code = {b["currency"]["code"]: b for b in balances.json()}
    assert by_code["USD"]["amount"] == pytest.approx(75.25)


async def test_user_can_set_display_currency_code(client):
    """``PATCH /api/me`` accepts ``display_currency_code`` (closed set
    of active fiat currencies). The value round-trips on the next
    ``GET /api/me``.
    """
    init = signed_init_data(10, "alice")
    await _bootstrap(client, tg_user_id=10, username="alice")

    resp = await client.patch(
        "/api/me",
        json={"display_currency_code": "uah"},
        headers=auth_headers(init),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_currency_code"] == "UAH"

    me = await client.get("/api/me", headers=auth_headers(init))
    assert me.json()["display_currency_code"] == "UAH"


async def test_user_can_clear_nullable_profile_fields(client):
    """``PATCH /api/me`` treats explicit null/empty values as clears.

    Omitted fields remain no-ops, but keys that are present with
    ``null`` must not be collapsed into the same branch as omitted keys.
    """
    init = signed_init_data(11, "clearable")
    await _bootstrap(client, tg_user_id=11, username="clearable")

    resp = await client.patch(
        "/api/me",
        json={
            "banner_url": "/media/banner/current.png",
            "photo_url": "https://cdn.example.test/avatar.png",
            "country": "us",
            "display_currency_code": "uah",
        },
        headers=auth_headers(init),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["banner_url"] == "/media/banner/current.png"
    assert body["photo_url"] == "https://cdn.example.test/avatar.png"
    assert body["country"] == "US"
    assert body["display_currency_code"] == "UAH"

    resp = await client.patch(
        "/api/me",
        json={"description": "unchanged nullable fields"},
        headers=auth_headers(init),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["banner_url"] == "/media/banner/current.png"
    assert body["photo_url"] == "https://cdn.example.test/avatar.png"
    assert body["country"] == "US"
    assert body["display_currency_code"] == "UAH"

    resp = await client.patch(
        "/api/me",
        json={
            "banner_url": None,
            "photo_url": None,
            "country": None,
            "display_currency_code": None,
        },
        headers=auth_headers(init),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["banner_url"] is None
    assert body["photo_url"] is None
    assert body["country"] is None
    assert body["display_currency_code"] is None

    resp = await client.patch(
        "/api/me",
        json={"country": "de", "display_currency_code": "rub"},
        headers=auth_headers(init),
    )
    assert resp.status_code == 200, resp.text

    resp = await client.patch(
        "/api/me",
        json={"country": "", "display_currency_code": ""},
        headers=auth_headers(init),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["country"] is None
    assert resp.json()["display_currency_code"] is None


async def test_user_display_currency_rejects_crypto(client):
    """The closed set is ``Currency.kind == 'fiat'``; a crypto code is
    rejected with a 400 so a stale frontend can't strand the column
    with an unrenderable value.
    """
    init = signed_init_data(10, "alice")
    await _bootstrap(client, tg_user_id=10, username="alice")

    resp = await client.patch(
        "/api/me",
        json={"display_currency_code": "USDT"},
        headers=auth_headers(init),
    )
    assert resp.status_code == 400


# ── Item 15 — kind=fiat filter ─────────────────────────────────────────────


async def test_wallet_currencies_kind_fiat_returns_only_fiat(client):
    """``GET /api/wallet/currencies?kind=fiat`` returns the three seed
    fiat rows (USD, UAH, RUB) and no crypto codes.
    """
    init = signed_init_data(10, "alice")
    await _bootstrap(client, tg_user_id=10, username="alice")

    resp = await client.get("/api/wallet/currencies?kind=fiat", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    codes = {c["code"] for c in resp.json()}
    assert {"USD", "UAH", "RUB"}.issubset(codes)
    for c in resp.json():
        assert c["kind"] == "fiat"


async def test_wallet_balances_kind_fiat_returns_only_fiat(client):
    init = signed_init_data(10, "alice")
    await _bootstrap(client, tg_user_id=10, username="alice")

    resp = await client.get("/api/wallet/balances?kind=fiat", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    for b in resp.json():
        assert b["currency"]["kind"] == "fiat"


async def test_wallet_currencies_kind_crypto_returns_only_crypto(client):
    """Symmetric check — ``kind=crypto`` filters the other way. Keeps
    the parameter from being a one-shot ``kind=fiat`` toggle.
    """
    init = signed_init_data(10, "alice")
    await _bootstrap(client, tg_user_id=10, username="alice")

    resp = await client.get("/api/wallet/currencies?kind=crypto", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    for c in resp.json():
        assert c["kind"] == "crypto"


async def test_wallet_currencies_no_kind_returns_all(client):
    init = signed_init_data(10, "alice")
    await _bootstrap(client, tg_user_id=10, username="alice")

    resp = await client.get("/api/wallet/currencies", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    kinds = {c["kind"] for c in resp.json()}
    assert {"fiat", "crypto"}.issubset(kinds)


# ── Item 16 — sweep across admin actions ───────────────────────────────────


async def test_admin_sweep_user_visible_changes(client):
    """End-to-end consistency sweep: admin sets stats, trust deposit,
    and credits a fiat balance — every change is visible to the
    target user without any server-side reconciliation step.
    """
    admin_init = signed_init_data(1, "admin")
    admin_id = await _bootstrap(client, tg_user_id=1, username="admin")
    await _promote_admin(admin_id)

    target_init = signed_init_data(2, "bob")
    target_id = await _bootstrap(client, tg_user_id=2, username="bob")

    # 1) Stats (deals counters).
    resp = await client.post(
        f"/api/admin/users/{target_id}/stats",
        json={"deals_total": 7, "deals_success": 5, "good": 5},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text

    # 2) Trust deposit.
    resp = await client.post(
        f"/api/admin/users/{target_id}/trust-deposit",
        json={"amount": "55"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text

    # 3) Fiat balance credit.
    resp = await client.post(
        f"/api/admin/wallets/{target_id}/adjust",
        json={"currency_code": "UAH", "amount": 200.0},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text

    me = await client.get("/api/me", headers=auth_headers(target_init))
    assert me.status_code == 200
    me_body = me.json()
    assert me_body["deals_count"] == 7
    assert me_body["deals_success"] == 5
    assert me_body["good"] == 5
    assert me_body["deposit"] == pytest.approx(55.0)

    balances = await client.get("/api/wallet/balances?kind=fiat", headers=auth_headers(target_init))
    by_code = {b["currency"]["code"]: b for b in balances.json()}
    assert by_code["UAH"]["amount"] == pytest.approx(200.0)
