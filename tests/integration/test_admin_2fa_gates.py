"""Negative tests for the 2FA-gate dependency installed on every
destructive admin endpoint in the security-audit follow-up PR.

The happy-path tests in ``test_admin_users.py`` / ``test_admin_deals.py``
already wrap their requests in ``with_totp(...)``, which short-circuits
``require_totp`` via the ``ADMIN_TOTP_BYPASS`` env var configured in
``conftest.py``. This module exercises the failure modes the bypass
hides:

* missing 2FA enrolment → 403
* enrolled but no ``X-Totp-Code`` header → 401
* enrolled but wrong code → 401
* enrolled + correct code → 200

We pick one endpoint per touched router so the cost stays bounded while
still proving the dependency is wired on every router:

* ``POST /api/admin/users/:id/ban``                     (users router)
* ``POST /api/admin/deals/:id/force-release``           (deals router)
* ``POST /api/admin/withdrawals/:id/decide``            (withdrawals router)
* ``POST /api/admin/wallets/:user_id/adjust``           (wallets router)
* ``POST /api/admin/deposits/:id/mark-paid``            (deposits router)
* ``POST /api/admin/broadcasts``                        (broadcasts router)
* ``PATCH /api/admin/settings``                         (settings router)
* ``POST /api/admin/services/:id/delete``               (content router)
* ``PUT /api/admin/categories``                         (taxonomy router)
* ``POST /api/admin/users/:id/unban``                   (users.unban — symmetric to ban)
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from backend.app.auth_2fa import totp_now
from backend.app.db import async_session
from backend.app.models import (
    Category,
    Currency,
    DealStatus,
    Service,
    User,
    UserBalance,
    WalletDeposit,
    WalletDepositStatus,
    WalletWithdrawal,
    WalletWithdrawStatus,
)
from tests.helpers import auth_headers, signed_init_data

# ── Test scaffolding ───────────────────────────────────────────────────


async def _bootstrap(client, *, tg_user_id: int, username: str) -> int:
    init = signed_init_data(tg_user_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _make_admin(client, tg: int = 1) -> tuple[str, int]:
    init = signed_init_data(tg, f"admin{tg}")
    uid = await _bootstrap(client, tg_user_id=tg, username=f"admin{tg}")
    async with async_session() as session:
        u = await session.get(User, uid)
        u.is_admin = True
        await session.commit()
    return init, uid


async def _enrol_2fa(client, admin_init: str) -> str:
    """Drive the real ``/api/admin/2fa/{setup,enable}`` flow and return
    the freshly-bound TOTP secret."""
    setup = await client.post("/api/admin/2fa/setup", headers=auth_headers(admin_init))
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    enable = await client.post(
        "/api/admin/2fa/enable",
        json={"secret": secret, "code": totp_now(secret)},
        headers=auth_headers(admin_init),
    )
    assert enable.status_code == 200, enable.text
    # Reset the replay counter so the next ``totp_now()`` call (in the
    # same 30s window) isn't rejected. In production callers simply
    # wait for the next window.
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.is_admin.is_(True)))).scalar_one()
        u.totp_last_counter = -1
        await session.commit()
    return secret


async def _real_totp_headers(client, admin_init: str, secret: str) -> dict[str, str]:
    """Issue a valid X-Totp-Code header and reset the replay counter so
    the next call inside the same test can mint another fresh code."""
    headers = {**auth_headers(admin_init), "X-Totp-Code": totp_now(secret)}
    return headers


async def _reset_replay(admin_id: int) -> None:
    async with async_session() as session:
        u = await session.get(User, admin_id)
        u.totp_last_counter = -1
        await session.commit()


# ── 1. users router — ban ──────────────────────────────────────────────


async def test_users_ban_requires_2fa(client):
    admin_init, admin_id = await _make_admin(client, tg=1)
    target_id = await _bootstrap(client, tg_user_id=2, username="bob")

    # No 2FA enrolled — dependency raises 403.
    resp = await client.post(
        f"/api/admin/users/{target_id}/ban",
        json={"reason": "spam"},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 403, resp.text

    secret = await _enrol_2fa(client, admin_init)

    # Enrolled but no header — 401.
    resp = await client.post(
        f"/api/admin/users/{target_id}/ban",
        json={"reason": "spam"},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 401, resp.text

    # Wrong code — 401.
    resp = await client.post(
        f"/api/admin/users/{target_id}/ban",
        json={"reason": "spam"},
        headers={**auth_headers(admin_init), "X-Totp-Code": "000000"},
    )
    assert resp.status_code == 401, resp.text

    # Correct code — 200, side-effects applied.
    await _reset_replay(admin_id)
    headers = await _real_totp_headers(client, admin_init, secret)
    resp = await client.post(
        f"/api/admin/users/{target_id}/ban",
        json={"reason": "spam"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    async with async_session() as session:
        target = await session.get(User, target_id)
        assert target.is_banned is True


# ── 2. deals router — force-release ────────────────────────────────────


async def test_deals_force_release_requires_2fa(client):
    """We don't need a real deal here — the dependency runs before the
    handler, so it raises 403 on a non-existent id when 2FA is missing.
    Once 2FA passes the handler returns 404 (deal not found), confirming
    the gate is the only thing standing between the caller and the
    handler body."""
    admin_init, admin_id = await _make_admin(client, tg=1)

    # No 2FA — 403.
    resp = await client.post(
        "/api/admin/deals/999/force-release",
        json={"reason": "x"},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 403, resp.text

    secret = await _enrol_2fa(client, admin_init)

    # No header — 401.
    resp = await client.post(
        "/api/admin/deals/999/force-release",
        json={"reason": "x"},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 401, resp.text

    # Correct code — gate passes, handler responds 404 (deal not found).
    await _reset_replay(admin_id)
    headers = await _real_totp_headers(client, admin_init, secret)
    resp = await client.post(
        "/api/admin/deals/999/force-release",
        json={"reason": "x"},
        headers=headers,
    )
    assert resp.status_code == 404, resp.text


# ── 3. withdrawals router — decide ─────────────────────────────────────


async def _seed_pending_withdrawal(user_id: int) -> int:
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        bal = UserBalance(user_id=user_id, currency_id=usdt.id, amount=100, locked=10)
        session.add(bal)
        w = WalletWithdrawal(
            user_id=user_id,
            currency_id=usdt.id,
            amount=10,
            address="UQA-test",
            status=WalletWithdrawStatus.pending,
        )
        session.add(w)
        await session.commit()
        await session.refresh(w)
        return w.id


async def test_withdrawals_decide_requires_2fa(client):
    admin_init, admin_id = await _make_admin(client, tg=1)
    target_id = await _bootstrap(client, tg_user_id=2, username="bob")
    wid = await _seed_pending_withdrawal(target_id)

    body = {"action": "reject", "note": "denied"}

    resp = await client.post(
        f"/api/admin/withdrawals/{wid}/decide",
        json=body,
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 403, resp.text

    secret = await _enrol_2fa(client, admin_init)

    resp = await client.post(
        f"/api/admin/withdrawals/{wid}/decide",
        json=body,
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 401, resp.text

    await _reset_replay(admin_id)
    headers = await _real_totp_headers(client, admin_init, secret)
    resp = await client.post(
        f"/api/admin/withdrawals/{wid}/decide",
        json=body,
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


# ── 4. wallets router — adjust ─────────────────────────────────────────


async def test_wallets_adjust_requires_2fa(client):
    admin_init, admin_id = await _make_admin(client, tg=1)
    target_id = await _bootstrap(client, tg_user_id=2, username="bob")

    payload = {
        "currency_code": "USDT",
        "amount": 50.0,
        "reason": "manual top-up",
    }

    resp = await client.post(
        f"/api/admin/wallets/{target_id}/adjust",
        json=payload,
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 403, resp.text

    secret = await _enrol_2fa(client, admin_init)

    resp = await client.post(
        f"/api/admin/wallets/{target_id}/adjust",
        json=payload,
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 401, resp.text

    await _reset_replay(admin_id)
    headers = await _real_totp_headers(client, admin_init, secret)
    resp = await client.post(
        f"/api/admin/wallets/{target_id}/adjust",
        json=payload,
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


# ── 5. deposits router — mark-paid ─────────────────────────────────────


async def _seed_pending_deposit(user_id: int) -> int:
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        d = WalletDeposit(
            user_id=user_id,
            currency_id=usdt.id,
            amount=Decimal("25"),
            status=WalletDepositStatus.pending,
            provider_invoice_id="manual-1",
            pay_url="",
        )
        session.add(d)
        await session.commit()
        await session.refresh(d)
        return d.id


async def test_deposits_mark_paid_requires_2fa(client):
    admin_init, admin_id = await _make_admin(client, tg=1)
    target_id = await _bootstrap(client, tg_user_id=2, username="bob")
    dep_id = await _seed_pending_deposit(target_id)

    resp = await client.post(
        f"/api/admin/deposits/{dep_id}/mark-paid",
        json={"reason": "x"},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 403, resp.text

    secret = await _enrol_2fa(client, admin_init)

    resp = await client.post(
        f"/api/admin/deposits/{dep_id}/mark-paid",
        json={"reason": "x"},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 401, resp.text

    await _reset_replay(admin_id)
    headers = await _real_totp_headers(client, admin_init, secret)
    resp = await client.post(
        f"/api/admin/deposits/{dep_id}/mark-paid",
        json={"reason": "x"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    async with async_session() as session:
        d = await session.get(WalletDeposit, dep_id)
        assert d.status == WalletDepositStatus.paid


# ── 6. broadcasts router — create ──────────────────────────────────────


async def test_broadcasts_create_requires_2fa(client):
    admin_init, admin_id = await _make_admin(client, tg=1)
    # Need at least one recipient so the handler has something to do.
    await _bootstrap(client, tg_user_id=2, username="bob")
    payload = {"body": "Hello", "dispatch_inapp": True, "dispatch_dm": False}

    resp = await client.post(
        "/api/admin/broadcasts",
        json=payload,
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 403, resp.text

    secret = await _enrol_2fa(client, admin_init)

    resp = await client.post(
        "/api/admin/broadcasts",
        json=payload,
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 401, resp.text

    resp = await client.post(
        "/api/admin/broadcasts",
        json=payload,
        headers={**auth_headers(admin_init), "X-Totp-Code": "000000"},
    )
    assert resp.status_code == 401, resp.text

    await _reset_replay(admin_id)
    headers = await _real_totp_headers(client, admin_init, secret)
    resp = await client.post(
        "/api/admin/broadcasts",
        json=payload,
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


# ── 7. settings router — update ────────────────────────────────────────


async def test_settings_update_requires_2fa(client):
    admin_init, admin_id = await _make_admin(client, tg=1)
    payload = {"deal_commission_percent": 3.5}

    resp = await client.patch(
        "/api/admin/settings",
        json=payload,
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 403, resp.text

    secret = await _enrol_2fa(client, admin_init)

    resp = await client.patch(
        "/api/admin/settings",
        json=payload,
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 401, resp.text

    await _reset_replay(admin_id)
    headers = await _real_totp_headers(client, admin_init, secret)
    resp = await client.patch(
        "/api/admin/settings",
        json=payload,
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


# ── 8. content router — delete_service ─────────────────────────────────


async def _seed_service(owner_id: int) -> int:
    async with async_session() as session:
        cat = (await session.execute(select(Category))).scalars().first()
        assert cat is not None
        s = Service(
            owner_id=owner_id,
            category_id=cat.id,
            title="t",
            description="d",
            price=10,
        )
        session.add(s)
        await session.commit()
        await session.refresh(s)
        return s.id


async def test_content_delete_service_requires_2fa(client):
    admin_init, admin_id = await _make_admin(client, tg=1)
    owner_id = await _bootstrap(client, tg_user_id=2, username="bob")
    sid = await _seed_service(owner_id)

    resp = await client.post(
        f"/api/admin/services/{sid}/delete",
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 403, resp.text

    secret = await _enrol_2fa(client, admin_init)

    resp = await client.post(
        f"/api/admin/services/{sid}/delete",
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 401, resp.text

    await _reset_replay(admin_id)
    headers = await _real_totp_headers(client, admin_init, secret)
    resp = await client.post(
        f"/api/admin/services/{sid}/delete",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    async with async_session() as session:
        assert await session.get(Service, sid) is None


# ── 9. taxonomy router — upsert_category ───────────────────────────────


async def test_taxonomy_upsert_category_requires_2fa(client):
    admin_init, admin_id = await _make_admin(client, tg=1)
    payload = {"slug": "gated-cat", "name": "Gated", "icon": "🔒"}

    resp = await client.put(
        "/api/admin/categories",
        json=payload,
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 403, resp.text

    secret = await _enrol_2fa(client, admin_init)

    resp = await client.put(
        "/api/admin/categories",
        json=payload,
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 401, resp.text

    await _reset_replay(admin_id)
    headers = await _real_totp_headers(client, admin_init, secret)
    resp = await client.put(
        "/api/admin/categories",
        json=payload,
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


# ── 10. users router — unban (symmetric to ban) ────────────────────────


async def test_users_unban_requires_2fa(client):
    admin_init, admin_id = await _make_admin(client, tg=1)
    target_id = await _bootstrap(client, tg_user_id=2, username="bob")
    async with async_session() as session:
        u = await session.get(User, target_id)
        u.is_banned = True
        u.ban_reason = "Спам"
        await session.commit()

    resp = await client.post(
        f"/api/admin/users/{target_id}/unban",
        json={},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 403, resp.text

    secret = await _enrol_2fa(client, admin_init)

    resp = await client.post(
        f"/api/admin/users/{target_id}/unban",
        json={},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 401, resp.text

    await _reset_replay(admin_id)
    headers = await _real_totp_headers(client, admin_init, secret)
    resp = await client.post(
        f"/api/admin/users/{target_id}/unban",
        json={},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    async with async_session() as session:
        target = await session.get(User, target_id)
        assert target.is_banned is False


# Local imports to keep DealStatus referenced when fixtures grow (silences
# unused-import warnings if the deals helper is ever inlined).
_ = DealStatus
