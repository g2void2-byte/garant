"""Tests for ``POST /api/admin/treasury/{id}/mark_sent``.

Manual reconciliation path for the Phase 2 → Phase 3 gap in
``treasury_withdraw``: CryptoBot processed the transfer, but the
final ``commit()`` never landed, so the row is still ``pending``
and counted against ``available``. Mirrors ``WalletWithdrawAdminDecideIn(
action="mark_sent")`` from ``routers/admin/withdrawals.py``.

Coverage:

* ``confirm=false`` → 400 before any DB write.
* Unknown ``withdrawal_id`` → 404.
* ``sent`` / ``failed`` rows → 409 (only ``pending`` is reconcilable).
* Happy path: row flips to ``sent`` with the operator-supplied
  ``cryptobot_transfer_id`` and a ``treasury.mark_sent`` audit row.
* ``cryptobot_transfer_id`` validator rejects non-digit input with 422.
* 2FA is required (handled by the ``TotpUser`` dependency — exercising
  via ``with_totp`` keeps that contract honest).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import (
    AdminAuditLog,
    Currency,
    TreasuryWithdrawal,
    User,
)
from tests.helpers import auth_headers, signed_init_data, with_totp


async def _bootstrap(client, *, tg_user_id: int, username: str) -> int:
    init = signed_init_data(tg_user_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _make_admin(client, *, tg: int) -> tuple[str, int]:
    init = signed_init_data(tg, f"admin{tg}")
    uid = await _bootstrap(client, tg_user_id=tg, username=f"admin{tg}")
    async with async_session() as session:
        u = await session.get(User, uid)
        u.is_admin = True
        await session.commit()
    return init, uid


async def _seed_pending_row(
    *,
    actor_id: int,
    status: str = "pending",
    address: str = "98765432",
    cryptobot_transfer_id: str | None = None,
) -> int:
    """Insert a treasury withdrawal row directly and return its id."""
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        row = TreasuryWithdrawal(
            actor_id=actor_id,
            currency_id=usdt.id,
            amount=Decimal("1.5"),
            address=address,
            status=status,
            note="seed for mark_sent test",
            cryptobot_transfer_id=cryptobot_transfer_id,
        )
        session.add(row)
        await session.commit()
        return row.id


# ── 2FA + confirm gate ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_sent_requires_confirm(client):
    admin_init, admin_id = await _make_admin(client, tg=9101)
    row_id = await _seed_pending_row(actor_id=admin_id)

    resp = await client.post(
        f"/api/admin/treasury/{row_id}/mark_sent",
        json={"confirm": False, "cryptobot_transfer_id": "12345"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 400, resp.text
    assert "confirm" in resp.text.lower()

    # Row untouched.
    async with async_session() as session:
        row = await session.get(TreasuryWithdrawal, row_id)
        assert row is not None
        assert row.status == "pending"
        assert row.cryptobot_transfer_id is None


@pytest.mark.asyncio
async def test_mark_sent_requires_2fa(client):
    """The endpoint depends on ``TotpUser``; without the TOTP enrolment
    the dependency short-circuits with 403 before any handler logic
    runs — the contract identical to all other ``TotpUser``-guarded
    admin endpoints (e.g. ``/withdraw``).
    """
    admin_init, admin_id = await _make_admin(client, tg=9102)
    row_id = await _seed_pending_row(actor_id=admin_id)

    resp = await client.post(
        f"/api/admin/treasury/{row_id}/mark_sent",
        json={"confirm": True},
        headers=auth_headers(admin_init),  # NO with_totp wrapper
    )
    assert resp.status_code == 403, resp.text


# ── Not-found / wrong-status ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_sent_unknown_id_404(client):
    admin_init, _ = await _make_admin(client, tg=9103)

    resp = await client.post(
        "/api/admin/treasury/9999999/mark_sent",
        json={"confirm": True},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_mark_sent_already_sent_409(client):
    """``sent`` is terminal — re-marking would write a duplicate audit
    row and confuse the operator. 409 mirrors the wallet-withdrawal
    handler.
    """
    admin_init, admin_id = await _make_admin(client, tg=9104)
    row_id = await _seed_pending_row(
        actor_id=admin_id,
        status="sent",
        cryptobot_transfer_id="111222",
    )

    resp = await client.post(
        f"/api/admin/treasury/{row_id}/mark_sent",
        json={"confirm": True, "cryptobot_transfer_id": "999"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 409, resp.text

    # State unchanged.
    async with async_session() as session:
        row = await session.get(TreasuryWithdrawal, row_id)
        assert row is not None
        assert row.status == "sent"
        # Operator-supplied id MUST NOT overwrite the existing one.
        assert row.cryptobot_transfer_id == "111222"


@pytest.mark.asyncio
async def test_mark_sent_failed_row_409(client):
    """``failed`` is deliberately terminal: the operator must issue a
    fresh withdrawal rather than resurrect a row whose Phase 2 raised
    ``CryptoPayError``. Otherwise the audit trail loses the ``failed``
    record.
    """
    admin_init, admin_id = await _make_admin(client, tg=9105)
    row_id = await _seed_pending_row(actor_id=admin_id, status="failed")

    resp = await client.post(
        f"/api/admin/treasury/{row_id}/mark_sent",
        json={"confirm": True, "cryptobot_transfer_id": "1"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 409, resp.text


# ── Validator on cryptobot_transfer_id ───────────────────────────────────


@pytest.mark.asyncio
async def test_mark_sent_non_digit_transfer_id_422(client):
    admin_init, admin_id = await _make_admin(client, tg=9106)
    row_id = await _seed_pending_row(actor_id=admin_id)

    resp = await client.post(
        f"/api/admin/treasury/{row_id}/mark_sent",
        json={"confirm": True, "cryptobot_transfer_id": "abc-not-a-number"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 422, resp.text


# ── Happy path ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_sent_happy_path(client):
    """Pending → sent, ``cryptobot_transfer_id`` recorded, audit row
    written, response reflects the flipped row.
    """
    admin_init, admin_id = await _make_admin(client, tg=9107)
    row_id = await _seed_pending_row(actor_id=admin_id, address="55501234")

    resp = await client.post(
        f"/api/admin/treasury/{row_id}/mark_sent",
        json={
            "confirm": True,
            "cryptobot_transfer_id": "888777",
            "note": "verified on CryptoBot dashboard",
        },
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == row_id
    assert body["status"] == "sent"
    assert body["cryptobot_transfer_id"] == "888777"
    assert "mark_sent: verified on CryptoBot dashboard" in body["note"]

    async with async_session() as session:
        row = await session.get(TreasuryWithdrawal, row_id)
        assert row is not None
        assert row.status == "sent"
        assert row.cryptobot_transfer_id == "888777"

        audit = (
            await session.execute(
                select(AdminAuditLog)
                .where(AdminAuditLog.action == "treasury.mark_sent")
                .order_by(AdminAuditLog.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        assert audit is not None
        assert audit.actor_id == admin_id
        assert audit.target_id == row_id
        assert audit.target_type == "treasury"
        assert audit.payload is not None
        assert audit.payload.get("cryptobot_transfer_id") == "888777"
        assert audit.payload.get("address") == "55501234"
        assert audit.payload.get("currency") == "USDT"


@pytest.mark.asyncio
async def test_mark_sent_without_transfer_id_still_advances(client):
    """``cryptobot_transfer_id`` is optional — sometimes the operator
    only has the spend_id receipt. The row must still advance to
    ``sent`` so the balance ledger is correct.
    """
    admin_init, admin_id = await _make_admin(client, tg=9108)
    row_id = await _seed_pending_row(actor_id=admin_id)

    resp = await client.post(
        f"/api/admin/treasury/{row_id}/mark_sent",
        json={"confirm": True, "note": "verified via spend_id only"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text

    async with async_session() as session:
        row = await session.get(TreasuryWithdrawal, row_id)
        assert row is not None
        assert row.status == "sent"
        assert row.cryptobot_transfer_id is None
