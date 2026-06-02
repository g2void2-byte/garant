"""Admin PR-CDE — finance routers (wallets / deposits / withdrawals).

Coverage:

* Wallets list/detail: paginated, search by username.
* Wallet adjust: applies signed delta with FOR UPDATE lock, writes audit
  log, transactional (no partial state).
* Deposits list filtering and ``mark_paid`` idempotency.
* Withdrawals decide: approve / reject / mark_sent with audit row.
* RBAC: every endpoint returns 403 to a non-admin.

P5 — the treasury overview / withdrawal flow has been removed; the
commission is now charged via the buyer's deposit invoice at deal
creation time (see ``services_deals.create_deal_with_topup``).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.app import services_wallet
from backend.app.db import async_session
from backend.app.models import (
    AdminAuditLog,
    Currency,
    User,
    UserBalance,
    WalletDeposit,
    WalletWithdrawal,
)
from backend.app.services_wallet import mark_withdrawal_auto_send_in_progress
from backend.app.time_utils import utcnow
from tests.helpers import auth_headers, signed_init_data, with_totp


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


async def _currency(code: str = "USDT") -> Currency:
    async with async_session() as session:
        cur = (await session.execute(select(Currency).where(Currency.code == code))).scalar_one()
        return cur


async def _credit(user_id: int, code: str, amount: float) -> None:
    from backend.app.services_wallet import (
        get_currency_by_code,
        get_or_create_balance,
    )

    async with async_session() as session:
        cur = await get_currency_by_code(session, code)
        bal = await get_or_create_balance(session, user_id, cur.id)
        bal.amount = float(amount)
        await session.commit()


# ── RBAC ────────────────────────────────────────────────────────────────


async def test_wallets_rbac_non_admin(client):
    init = signed_init_data(10, "alice")
    await _bootstrap(client, tg_user_id=10, username="alice")
    resp = await client.get("/api/admin/wallets", headers=auth_headers(init))
    assert resp.status_code == 403


async def test_deposits_rbac_non_admin(client):
    init = signed_init_data(10, "alice")
    await _bootstrap(client, tg_user_id=10, username="alice")
    resp = await client.get("/api/admin/deposits", headers=auth_headers(init))
    assert resp.status_code == 403


async def test_withdrawals_rbac_non_admin(client):
    init = signed_init_data(10, "alice")
    await _bootstrap(client, tg_user_id=10, username="alice")
    resp = await client.get("/api/admin/withdrawals", headers=auth_headers(init))
    assert resp.status_code == 403


# ── Wallets ─────────────────────────────────────────────────────────────


async def test_wallets_list_returns_users(client):
    admin_init, _ = await _make_admin(client, tg=1)
    bob_id = await _bootstrap(client, tg_user_id=2, username="bob")
    await _credit(bob_id, "USDT", 100.0)

    resp = await client.get("/api/admin/wallets", headers=auth_headers(admin_init))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    bob_row = next(it for it in body["items"] if it["user_id"] == bob_id)
    usdt = next(b for b in bob_row["balances"] if b["currency_code"] == "USDT")
    assert float(usdt["amount"]) == pytest.approx(100.0)


async def test_wallet_adjust_credits_and_audits(client):
    admin_init, _ = await _make_admin(client, tg=1)
    bob_id = await _bootstrap(client, tg_user_id=2, username="bob")

    resp = await client.post(
        f"/api/admin/wallets/{bob_id}/adjust",
        json={"currency_code": "USDT", "amount": 50.5, "reason": "manual top-up"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert float(body["amount"]) == pytest.approx(50.5)
    assert body["currency_code"] == "USDT"

    async with async_session() as session:
        cur = await _currency("USDT")
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == bob_id,
                    UserBalance.currency_id == cur.id,
                )
            )
        ).scalar_one()
        assert float(bal.amount) == pytest.approx(50.5)
        audits = (
            (
                await session.execute(
                    select(AdminAuditLog).where(AdminAuditLog.action == "wallet.adjust")
                )
            )
            .scalars()
            .all()
        )
        assert len(audits) == 1
        assert audits[0].target_id == bob_id


async def test_wallet_adjust_debit_signed(client):
    admin_init, _ = await _make_admin(client, tg=1)
    bob_id = await _bootstrap(client, tg_user_id=2, username="bob")
    await _credit(bob_id, "USDT", 100.0)

    resp = await client.post(
        f"/api/admin/wallets/{bob_id}/adjust",
        json={"currency_code": "USDT", "amount": -30.0},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    assert float(resp.json()["amount"]) == pytest.approx(70.0)


# ── Deposits ────────────────────────────────────────────────────────────


async def test_deposits_list_empty(client):
    admin_init, _ = await _make_admin(client, tg=1)
    resp = await client.get("/api/admin/deposits", headers=auth_headers(admin_init))
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


async def test_deposits_mark_paid_idempotent(client):
    admin_init, _ = await _make_admin(client, tg=1)
    bob_id = await _bootstrap(client, tg_user_id=2, username="bob")

    # Create a pending deposit directly in DB.
    cur = await _currency("USDT")
    async with async_session() as session:
        dep = WalletDeposit(
            user_id=bob_id,
            currency_id=cur.id,
            amount=Decimal("10.00"),
            status="pending",
            provider_invoice_id="test-inv-1",
            pay_url="https://example/pay",
        )
        session.add(dep)
        await session.commit()
        dep_id = dep.id

    r1 = await client.post(
        f"/api/admin/deposits/{dep_id}/mark-paid",
        json={},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "paid"

    r2 = await client.post(
        f"/api/admin/deposits/{dep_id}/mark-paid",
        json={},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert r2.status_code in (200, 400)
    async with async_session() as session:
        cur2 = await _currency("USDT")
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == bob_id,
                    UserBalance.currency_id == cur2.id,
                )
            )
        ).scalar_one()
        # Credited exactly once even if mark-paid is replayed.
        assert float(bal.amount) == pytest.approx(10.0)


# ── Withdrawals ─────────────────────────────────────────────────────────


async def test_withdrawals_decide_reject_returns_funds(client):
    admin_init, _ = await _make_admin(client, tg=1)
    bob_id = await _bootstrap(client, tg_user_id=2, username="bob")
    cur = await _currency("USDT")
    async with async_session() as session:
        wd = WalletWithdrawal(
            user_id=bob_id,
            currency_id=cur.id,
            amount=Decimal("20.0"),
            address="bob-wallet-address",
            status="pending",
        )
        session.add(wd)
        # Reserve in locked
        bal = UserBalance(user_id=bob_id, currency_id=cur.id, amount=0, locked=20)
        session.add(bal)
        await session.commit()
        wd_id = wd.id

    resp = await client.post(
        f"/api/admin/withdrawals/{wd_id}/decide",
        json={"action": "reject", "note": "wrong address"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"
    async with async_session() as session:
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == bob_id,
                    UserBalance.currency_id == cur.id,
                )
            )
        ).scalar_one()
        assert float(bal.amount) == pytest.approx(20.0)
        assert float(bal.locked) == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("status", "action"),
    [
        ("pending", "approve"),
        ("pending", "reject"),
        ("approved", "reject"),
        ("approved", "mark_sent"),
    ],
)
async def test_withdrawals_auto_send_in_progress_blocks_admin_race(
    client,
    status: str,
    action: str,
):
    admin_init, _ = await _make_admin(client, tg=1)
    bob_id = await _bootstrap(client, tg_user_id=2, username="bob")
    cur = await _currency("USDT")
    async with async_session() as session:
        wd = WalletWithdrawal(
            user_id=bob_id,
            currency_id=cur.id,
            amount=Decimal("20.0"),
            address=None,
            status=status,
            admin_note=mark_withdrawal_auto_send_in_progress("auto"),
        )
        session.add(wd)
        session.add(UserBalance(user_id=bob_id, currency_id=cur.id, amount=0, locked=20))
        await session.commit()
        wd_id = wd.id

    resp = await client.post(
        f"/api/admin/withdrawals/{wd_id}/decide",
        json={"action": action, "note": "operator race"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "Авто-отправка вывода уже выполняется"

    async with async_session() as session:
        wd_row = await session.get(WalletWithdrawal, wd_id)
        assert wd_row is not None
        assert wd_row.status.value == status
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == bob_id,
                    UserBalance.currency_id == cur.id,
                )
            )
        ).scalar_one()
        assert float(bal.amount) == pytest.approx(0.0)
        assert float(bal.locked) == pytest.approx(20.0)


async def test_withdrawals_stale_sweep_skips_recent_auto_send_marker(
    client,
    monkeypatch,
):
    bob_id = await _bootstrap(client, tg_user_id=2, username="bob")
    cur = await _currency("USDT")
    async with async_session() as session:
        wd = WalletWithdrawal(
            user_id=bob_id,
            currency_id=cur.id,
            amount=Decimal("20.0"),
            address=None,
            status="pending",
            admin_note=mark_withdrawal_auto_send_in_progress("auto"),
            created_at=utcnow() - timedelta(seconds=2),
        )
        session.add(wd)
        session.add(UserBalance(user_id=bob_id, currency_id=cur.id, amount=0, locked=20))
        await session.commit()
        wd_id = wd.id

    class _NoTransfersCryptoPay:
        calls = 0

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def __aenter__(self) -> _NoTransfersCryptoPay:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def get_transfers(self, **_kwargs: object) -> list[object]:
            type(self).calls += 1
            return []

    monkeypatch.setattr(services_wallet.settings, "cryptobot_token", "12345:test-real-token")
    monkeypatch.setattr(services_wallet.settings, "wallet_withdrawal_stale_seconds", 1)
    monkeypatch.setattr(services_wallet, "CryptoPay", _NoTransfersCryptoPay)

    async with async_session() as session:
        reconciled = await services_wallet.sweep_stale_withdrawals(session)

    assert reconciled == 0
    assert _NoTransfersCryptoPay.calls == 0

    async with async_session() as session:
        wd_row = await session.get(WalletWithdrawal, wd_id)
        assert wd_row is not None
        assert wd_row.status.value == "pending"
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == bob_id,
                    UserBalance.currency_id == cur.id,
                )
            )
        ).scalar_one()
        assert float(bal.amount) == pytest.approx(0.0)
        assert float(bal.locked) == pytest.approx(20.0)


async def test_withdrawals_counters_per_status(client):
    admin_init, _ = await _make_admin(client, tg=1)
    bob_id = await _bootstrap(client, tg_user_id=2, username="bob")
    cur = await _currency("USDT")
    async with async_session() as session:
        for status in ("pending", "pending", "rejected"):
            session.add(
                WalletWithdrawal(
                    user_id=bob_id,
                    currency_id=cur.id,
                    amount=Decimal("1.0"),
                    address="addr",
                    status=status,
                )
            )
        await session.commit()
    resp = await client.get(
        "/api/admin/withdrawals?status=pending", headers=auth_headers(admin_init)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["counters"].get("pending", 0) >= 2
