"""Regression tests for the audit residual 4.2 (HIGH) — `decide_withdrawal`
no longer holds the `wallet_withdrawals` row lock through the CryptoBot
`transfer` HTTP roundtrip.

Two paths exercised:

* **happy auto-send**: ``AppSettings.auto_withdraw_enabled=True`` +
  CryptoBot token configured → admin POST ``/decide`` runs the three-
  phase commit (mark ``approved`` → HTTP outside any lock → mark
  ``sent``, decrement locked, audit), returns a row in ``sent`` state.
* **CryptoBot error**: same setup but the stubbed ``CryptoPay.transfer``
  raises ``CryptoPayError`` → 502 + row stays in ``approved`` (the
  operator can retry manually via ``mark_sent`` and CryptoBot's
  ``spend_id`` dedupe makes the retry safe).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

import backend.app.routers.admin.withdrawals as wd_router
from backend.app.config import settings as app_settings_env
from backend.app.cryptopay import CryptoPayError, Transfer
from backend.app.db import async_session
from backend.app.models import (
    AdminAuditLog,
    AppSettings,
    Currency,
    User,
    UserBalance,
    WalletWithdrawal,
    WalletWithdrawStatus,
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


async def _seed_auto_mode_with_pending_withdrawal(user_id: int) -> tuple[int, str]:
    """Set ``auto_withdraw_enabled=True`` and create a pending withdrawal.

    Returns ``(withdrawal_id, currency_code)``.
    """
    async with async_session() as session:
        # Upsert the single-row AppSettings flag.
        app_row = (
            await session.execute(select(AppSettings).order_by(AppSettings.id).limit(1))
        ).scalar_one_or_none()
        if app_row is None:
            app_row = AppSettings(auto_withdraw_enabled=True)
            session.add(app_row)
        else:
            app_row.auto_withdraw_enabled = True
        await session.flush()

        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        bal = UserBalance(user_id=user_id, currency_id=usdt.id, amount=80, locked=20)
        session.add(bal)
        wd = WalletWithdrawal(
            user_id=user_id,
            currency_id=usdt.id,
            amount=Decimal("20.0"),
            address="user-wallet-address",
            status=WalletWithdrawStatus.pending,
        )
        session.add(wd)
        await session.commit()
        return wd.id, usdt.code


class _StubCryptoPay:
    """Drop-in replacement for ``CryptoPay`` that records arguments and
    returns a deterministic ``Transfer``.

    Crucially, ``transfer()`` is an async function that does NOT touch
    the DB — its body sleeps zero seconds — so the test deterministically
    captures the call shape from the audit-fix two-phase commit.
    """

    captured: list[dict] = []

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def __aenter__(self) -> "_StubCryptoPay":
        return self

    async def __aexit__(self, *_exc) -> None:  # noqa: ANN001
        return None

    async def transfer(self, **kwargs) -> Transfer:
        _StubCryptoPay.captured.append(kwargs)
        return Transfer(
            transfer_id=999_001,
            user_id=kwargs["user_id"],
            asset=kwargs["asset"],
            amount=kwargs["amount"],
            status="completed",
            completed_at=None,
        )


class _ErrorCryptoPay(_StubCryptoPay):
    async def transfer(self, **kwargs) -> Transfer:
        _StubCryptoPay.captured.append(kwargs)
        raise CryptoPayError("Crypto Pay HTTP error: simulated upstream 500")


async def test_auto_send_happy_path_marks_sent_and_drops_locked(client, monkeypatch):
    """Audit 4.2 — auto-send path commits in three phases and ends in ``sent``."""
    admin_init, admin_id = await _make_admin(client, tg=1)
    user_id = await _bootstrap(client, tg_user_id=2, username="bob")
    wid, currency_code = await _seed_auto_mode_with_pending_withdrawal(user_id)

    _StubCryptoPay.captured = []
    monkeypatch.setattr(wd_router, "CryptoPay", _StubCryptoPay)
    monkeypatch.setattr(app_settings_env, "cryptobot_token", "12345:test-real-token")

    resp = await client.post(
        f"/api/admin/withdrawals/{wid}/decide",
        json={"action": "approve", "note": "auto"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "sent", body

    # CryptoBot was called exactly once with the expected idempotency key.
    assert len(_StubCryptoPay.captured) == 1
    call = _StubCryptoPay.captured[0]
    assert call["spend_id"] == f"wd:{wid}"
    assert call["asset"] == currency_code
    assert Decimal(call["amount"]) == Decimal("20.0")

    # Row reached ``sent`` and ``locked`` was decremented to zero.
    async with async_session() as session:
        wd_row = await session.get(WalletWithdrawal, wid)
        assert wd_row is not None
        assert wd_row.status == WalletWithdrawStatus.sent
        assert wd_row.processed_at is not None

        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == user_id,
                    UserBalance.currency_id == wd_row.currency_id,
                )
            )
        ).scalar_one()
        # 20 was locked; auto-send drains that, leaves ``amount`` at the
        # pre-test value (80) because the user already debited at
        # withdraw-request time.
        assert float(bal.locked) == pytest.approx(0.0)
        assert float(bal.amount) == pytest.approx(80.0)

        # Audit row written with the CryptoBot transfer_id.
        audit_row = (
            await session.execute(
                select(AdminAuditLog)
                .where(AdminAuditLog.action == "withdrawal.auto_send")
                .order_by(AdminAuditLog.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        assert audit_row is not None
        assert audit_row.actor_id == admin_id
        assert audit_row.payload is not None
        assert audit_row.payload.get("cryptobot_transfer_id") == 999_001
        assert audit_row.payload.get("auto") is True


async def test_auto_send_cryptobot_failure_leaves_row_approved(client, monkeypatch):
    """Audit 4.2 — when CryptoBot returns an error, the row stays at
    ``approved`` (the operator's retry path via ``mark_sent`` is still
    available, and ``spend_id`` dedupe makes the retry safe).
    """
    admin_init, admin_id = await _make_admin(client, tg=1)
    user_id = await _bootstrap(client, tg_user_id=2, username="bob")
    wid, _ = await _seed_auto_mode_with_pending_withdrawal(user_id)

    _StubCryptoPay.captured = []
    monkeypatch.setattr(wd_router, "CryptoPay", _ErrorCryptoPay)
    monkeypatch.setattr(app_settings_env, "cryptobot_token", "12345:test-real-token")

    resp = await client.post(
        f"/api/admin/withdrawals/{wid}/decide",
        json={"action": "approve", "note": "auto"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 502, resp.text

    async with async_session() as session:
        wd_row = await session.get(WalletWithdrawal, wid)
        assert wd_row is not None
        # Phase 1 committed ``approved``; Phase 2 failed; Phase 3 never
        # ran → row is observable in ``approved``.
        assert wd_row.status == WalletWithdrawStatus.approved

        # User's ``locked`` is unchanged because Phase 3 never debited it.
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == user_id,
                    UserBalance.currency_id == wd_row.currency_id,
                )
            )
        ).scalar_one()
        assert float(bal.locked) == pytest.approx(20.0)

        # The failure is recorded in the audit log with the right action.
        audit_row = (
            await session.execute(
                select(AdminAuditLog)
                .where(AdminAuditLog.action == "withdrawal.auto_send_failed")
                .order_by(AdminAuditLog.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        assert audit_row is not None
        assert audit_row.actor_id == admin_id
