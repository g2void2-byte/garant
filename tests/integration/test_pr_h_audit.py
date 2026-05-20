"""PR-H — audit fixes: ``refunded`` deposit status + broadcast soft-delete.

* **M-16** — verify ``POST /api/admin/deposits/:id/refund`` now sets
  ``status='refunded'`` instead of conflating with the CryptoBot-side
  ``expired`` state.

* **L-10** — verify ``DELETE /api/admin/broadcasts/:id`` soft-deletes
  the row (stamps ``deleted_at``) and that the row no longer surfaces
  in the public list endpoint but is still on disk for the audit log
  FK to point at.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import (
    Broadcast,
    Currency,
    User,
    UserBalance,
    WalletDeposit,
    WalletDepositStatus,
)
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


# ── M-16 ──────────────────────────────────────────────────────────────────


async def test_refund_sets_status_to_refunded_not_expired(client):
    """The refund endpoint must use the new dedicated ``refunded`` value.

    Pre-PR-H this set ``status='expired'``, which conflated an admin
    reversal with CryptoBot-side invoice expiry on the admin badge
    and in the ``WalletDeposit.status`` analytics filter.
    """
    admin_init, _ = await _make_admin(client, tg=1)
    user_id = await _bootstrap(client, tg_user_id=2, username="bob")

    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        # Pre-seed: paid deposit + matching credited balance, so the
        # refund's balance-deduction precondition is met.
        deposit = WalletDeposit(
            user_id=user_id,
            currency_id=usdt.id,
            amount=Decimal("50"),
            status=WalletDepositStatus.paid,
            provider_invoice_id="cb-refund-1",
            pay_url="",
        )
        session.add(deposit)
        bal = UserBalance(
            user_id=user_id,
            currency_id=usdt.id,
            amount=Decimal("50"),
        )
        session.add(bal)
        await session.commit()
        deposit_id = deposit.id

    resp = await client.post(
        f"/api/admin/deposits/{deposit_id}/refund",
        json={"reason": "test"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "refunded"

    async with async_session() as session:
        d = await session.get(WalletDeposit, deposit_id)
        assert d.status == WalletDepositStatus.refunded
        assert d.paid_at is None  # refund clears paid_at
        # Balance was deducted back out.
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == user_id, UserBalance.currency_id == usdt.id
                )
            )
        ).scalar_one()
        assert Decimal(str(bal.amount)) == Decimal("0")


async def test_refund_listed_under_refunded_filter(client):
    """The admin deposits list ``?status=refunded`` returns refunded rows."""
    admin_init, _ = await _make_admin(client, tg=1)
    user_id = await _bootstrap(client, tg_user_id=2, username="bob")

    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        session.add(
            WalletDeposit(
                user_id=user_id,
                currency_id=usdt.id,
                amount=Decimal("10"),
                status=WalletDepositStatus.refunded,
                provider_invoice_id="cb-refund-2",
                pay_url="",
            )
        )
        await session.commit()

    resp = await client.get(
        "/api/admin/deposits?status=refunded",
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 200, resp.text
    statuses = {item["status"] for item in resp.json()["items"]}
    assert "refunded" in statuses


# ── L-10 ──────────────────────────────────────────────────────────────────


async def test_broadcast_delete_is_soft(client):
    """Deletion stamps ``deleted_at`` and hides the row from the list,
    but the row stays in the DB so the audit log FK target survives.
    """
    admin_init, _ = await _make_admin(client, tg=1)
    await _bootstrap(client, tg_user_id=2, username="bob")

    send = await client.post(
        "/api/admin/broadcasts",
        json={"body": "Hello", "dispatch_inapp": True, "dispatch_dm": False},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert send.status_code == 200, send.text
    bcast_id = send.json()["id"]

    listed = await client.get("/api/admin/broadcasts", headers=auth_headers(admin_init))
    assert any(item["id"] == bcast_id for item in listed.json()["items"])

    resp = await client.delete(
        f"/api/admin/broadcasts/{bcast_id}",
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text

    # Hidden from the list.
    listed2 = await client.get("/api/admin/broadcasts", headers=auth_headers(admin_init))
    assert all(item["id"] != bcast_id for item in listed2.json()["items"])

    # Still on disk with a non-null ``deleted_at``.
    async with async_session() as session:
        b = await session.get(Broadcast, bcast_id)
        assert b is not None, "broadcast row must survive soft-delete"
        assert b.deleted_at is not None


async def test_broadcast_delete_idempotent_returns_404(client):
    """Hitting DELETE on an already-deleted broadcast returns 404.

    The row is on disk but isn't a valid target for further mutation.
    """
    admin_init, _ = await _make_admin(client, tg=1)
    await _bootstrap(client, tg_user_id=2, username="bob")

    send = await client.post(
        "/api/admin/broadcasts",
        json={"body": "x", "dispatch_inapp": True, "dispatch_dm": False},
        headers=with_totp(auth_headers(admin_init)),
    )
    bcast_id = send.json()["id"]

    first = await client.delete(
        f"/api/admin/broadcasts/{bcast_id}",
        headers=with_totp(auth_headers(admin_init)),
    )
    assert first.status_code == 200, first.text

    again = await client.delete(
        f"/api/admin/broadcasts/{bcast_id}",
        headers=with_totp(auth_headers(admin_init)),
    )
    assert again.status_code == 404, again.text
