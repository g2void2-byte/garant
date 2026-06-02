"""I-11 — coverage gap-fill for ``POST /api/admin/deposits/{id}/refund``.

The refund handler is the money-reversal counterpart of
``mark-paid``: it debits the user's spendable balance and flips the
deposit row to ``refunded``. ``test_admin_finance.py`` covers the
mark-paid path; ``refund`` had no test, despite being the higher-risk
of the two (it moves money OUT of a user's wallet, mark-paid moves
money IN).

We pin:
1. Happy path — paid → refunded; balance debited; audit log emitted.
2. Insufficient-balance guard — refund refused when the user has spent
   the deposited funds, so we don't accidentally drop the user's
   ``balance`` below zero.
3. State guard — refund of a non-``paid`` deposit (e.g. still
   ``pending``) is refused.
4. RBAC — non-admin caller bounces with 403.
5. 404 for unknown deposit id.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import (
    AdminAuditLog,
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


async def _currency(code: str) -> Currency:
    async with async_session() as session:
        return (await session.execute(select(Currency).where(Currency.code == code))).scalar_one()


async def _seed_paid_deposit(
    *, user_id: int, code: str, amount: str, credit_balance: bool = True
) -> int:
    """Insert a ``paid`` deposit and (optionally) credit the matching
    ``UserBalance`` row to the same amount, mirroring the post-credit
    state the mark-paid handler leaves behind."""
    async with async_session() as session:
        cur = (await session.execute(select(Currency).where(Currency.code == code))).scalar_one()
        d = WalletDeposit(
            user_id=user_id,
            currency_id=cur.id,
            amount=Decimal(amount),
            status=WalletDepositStatus.paid,
            provider_invoice_id=f"test-{user_id}-{amount}",
        )
        session.add(d)
        if credit_balance:
            bal = UserBalance(
                user_id=user_id,
                currency_id=cur.id,
                amount=Decimal(amount),
                locked=Decimal("0"),
            )
            session.add(bal)
        await session.commit()
        return d.id


async def test_refund_debits_balance_and_marks_refunded(client):
    admin_init, _ = await _make_admin(client, tg=1)
    bob_id = await _bootstrap(client, tg_user_id=2, username="bob_refund")
    dep_id = await _seed_paid_deposit(user_id=bob_id, code="USDT", amount="40")

    resp = await client.post(
        f"/api/admin/deposits/{dep_id}/refund",
        json={"reason": "fraud"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "refunded"
    assert body["id"] == dep_id

    async with async_session() as session:
        cur = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == bob_id,
                    UserBalance.currency_id == cur.id,
                )
            )
        ).scalar_one()
        assert Decimal(bal.amount) == Decimal("0")

        audits = (
            (
                await session.execute(
                    select(AdminAuditLog).where(AdminAuditLog.action == "deposit.refund")
                )
            )
            .scalars()
            .all()
        )
        assert len(audits) == 1
        log = audits[0]
        assert log.target_id == dep_id
        assert (log.payload or {}).get("currency") == "USDT"
        # Numeric → SQLAlchemy serialises Decimal at column precision,
        # so we compare numerically rather than by string format.
        assert Decimal((log.payload or {}).get("amount")) == Decimal("40")
        assert log.reason == "fraud"


async def test_mark_paid_rejects_refunded_deposit(client):
    """A manual mark-paid must not undo an admin refund."""
    admin_init, _ = await _make_admin(client, tg=1)
    bob_id = await _bootstrap(client, tg_user_id=21, username="bob_refunded_mark_paid")
    cur = await _currency("USDT")
    async with async_session() as session:
        d = WalletDeposit(
            user_id=bob_id,
            currency_id=cur.id,
            amount=Decimal("12"),
            status=WalletDepositStatus.refunded,
            provider_invoice_id="refunded-mark-paid-test-1",
            pay_url="http://example.com/pay",
        )
        session.add(d)
        session.add(
            UserBalance(
                user_id=bob_id,
                currency_id=cur.id,
                amount=Decimal("0"),
                locked=Decimal("0"),
            )
        )
        await session.commit()
        dep_id = d.id

    resp = await client.post(
        f"/api/admin/deposits/{dep_id}/mark-paid",
        json={"reason": "retry"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "Депозит уже возвращен"

    async with async_session() as session:
        d = await session.get(WalletDeposit, dep_id)
        assert d is not None
        assert d.status == WalletDepositStatus.refunded
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == bob_id,
                    UserBalance.currency_id == cur.id,
                )
            )
        ).scalar_one()
        assert Decimal(str(bal.amount)) == Decimal("0E-8")


async def test_refund_rejected_when_user_already_spent_funds(client):
    """If the user has spent the deposit, ``balance < amount``. The
    handler must refuse the refund so we don't push the balance
    negative."""
    admin_init, _ = await _make_admin(client, tg=1)
    bob_id = await _bootstrap(client, tg_user_id=3, username="bob_spent")
    dep_id = await _seed_paid_deposit(
        user_id=bob_id, code="USDT", amount="50", credit_balance=False
    )
    # Manually credit only PART of the deposit so balance < amount.
    cur = await _currency("USDT")
    async with async_session() as session:
        session.add(
            UserBalance(
                user_id=bob_id,
                currency_id=cur.id,
                amount=Decimal("10"),
                locked=Decimal("0"),
            )
        )
        await session.commit()

    resp = await client.post(
        f"/api/admin/deposits/{dep_id}/refund",
        json={"reason": "test"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 400, resp.text
    # Balance was NOT touched.
    async with async_session() as session:
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == bob_id,
                    UserBalance.currency_id == cur.id,
                )
            )
        ).scalar_one()
        assert Decimal(bal.amount) == Decimal("10")
        # No audit row written for the rejected operation.
        audits = (
            (
                await session.execute(
                    select(AdminAuditLog).where(AdminAuditLog.action == "deposit.refund")
                )
            )
            .scalars()
            .all()
        )
        assert audits == []


async def test_refund_rejected_when_deposit_is_pending(client):
    admin_init, _ = await _make_admin(client, tg=1)
    bob_id = await _bootstrap(client, tg_user_id=4, username="bob_pending")
    cur = await _currency("USDT")
    async with async_session() as session:
        d = WalletDeposit(
            user_id=bob_id,
            currency_id=cur.id,
            amount=Decimal("5"),
            status=WalletDepositStatus.pending,
            provider_invoice_id="pending-test-1",
        )
        session.add(d)
        await session.commit()
        dep_id = d.id

    resp = await client.post(
        f"/api/admin/deposits/{dep_id}/refund",
        json={"reason": "x"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 400


async def test_refund_404_for_unknown_id(client):
    admin_init, _ = await _make_admin(client, tg=1)
    resp = await client.post(
        "/api/admin/deposits/99999999/refund",
        json={"reason": "x"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 404


async def test_refund_rbac_non_admin(client):
    init = signed_init_data(20, "alice_refund")
    await _bootstrap(client, tg_user_id=20, username="alice_refund")
    resp = await client.post(
        "/api/admin/deposits/1/refund",
        json={"reason": "x"},
        headers=with_totp(auth_headers(init)),
    )
    assert resp.status_code == 403
