"""Audit follow-up regression suite (2026-05-19) — T1/T2 on
``routers/admin/treasury.py``.

Maps 1:1 to ``audit-followup-2026-05-19.md §3.A``:

* **T1** — silent admin self-payout when ``body.address`` was not a
  digit. ``CryptoPay.transfer`` accepts only Telegram ``user_id``;
  pre-fix the handler silently fell back to ``admin.tg_user_id`` for
  any non-digit input, so an operator who pasted a "Txxx…" wallet
  address quietly paid themselves while ``wallet_treasury_withdrawals``
  recorded the wallet string. Coverage:

    * The schema validator rejects non-digit input with 422 instead of
      letting the handler reach the silent fallback.
    * The handler actually passes the *operator-supplied* ``user_id``
      to ``cp.transfer`` — not ``admin.tg_user_id``.

* **T2** — ``pg_advisory_xact_lock`` was held through the CryptoBot
  HTTP roundtrip, so a slow upstream queued every concurrent admin
  withdrawal on the same currency behind the in-flight transfer.
  Coverage:

    * Happy path: three-phase commit lands the row in ``sent`` with
      the right ``spend_id``/``user_id`` and an audit row.
    * CryptoBot failure: row reaches ``failed`` after Phase 3,
      ``treasury.withdraw_failed`` audit row written, 502 returned.
    * Concurrency: while Phase 2 is in flight (lock released, row
      ``pending``), a second admin sees the ``pending`` row counted
      against ``available`` and gets 400 "недостаточно комиссии".
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

import backend.app.routers.admin.treasury as treasury_router
from backend.app.config import settings as app_settings
from backend.app.cryptopay import CryptoPayError, Transfer
from backend.app.db import async_session
from backend.app.models import (
    AdminAuditLog,
    Currency,
    Deal,
    DealStatus,
    TreasuryWithdrawal,
    User,
)
from backend.app.time_utils import utcnow
from tests.helpers import auth_headers, signed_init_data, with_totp

# ── Bootstrap helpers ─────────────────────────────────────────────────────


async def _bootstrap(client, *, tg_user_id: int, username: str) -> int:
    init = signed_init_data(tg_user_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _make_admin(client, *, tg: int) -> tuple[str, int, int]:
    """Return ``(init_data, user_pk, tg_user_id)`` for an admin user."""
    init = signed_init_data(tg, f"admin{tg}")
    uid = await _bootstrap(client, tg_user_id=tg, username=f"admin{tg}")
    async with async_session() as session:
        u = await session.get(User, uid)
        u.is_admin = True
        await session.commit()
    return init, uid, tg


async def _seed_completed_deal_with_commission(
    *,
    buyer_id: int,
    seller_id: int,
    commission: Decimal,
) -> None:
    """Insert a completed deal contributing ``commission`` to the
    treasury accrual for USDT.
    """
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        deal = Deal(
            buyer_id=buyer_id,
            seller_id=seller_id,
            currency_id=usdt.id,
            amount=Decimal("100.00"),
            commission_amount=commission,
            status=DealStatus.completed,
            description="seed for T1/T2 tests",
            completed_at=utcnow(),
        )
        session.add(deal)
        await session.commit()


# ── Stubbed CryptoPay clients ─────────────────────────────────────────────


class _CapturingCryptoPay:
    """``CryptoPay`` drop-in that records ``transfer`` kwargs and
    returns a deterministic ``Transfer``.
    """

    captured: list[dict] = []

    def __init__(self, *_a, **_kw) -> None:
        pass

    async def __aenter__(self) -> "_CapturingCryptoPay":
        return self

    async def __aexit__(self, *_exc) -> None:  # noqa: ANN001
        return None

    async def transfer(self, **kwargs) -> Transfer:
        _CapturingCryptoPay.captured.append(kwargs)
        return Transfer(
            transfer_id=777_001,
            user_id=kwargs["user_id"],
            asset=kwargs["asset"],
            amount=kwargs["amount"],
            status="completed",
            completed_at=None,
        )


class _ErrorCryptoPay:
    """``CryptoPay`` drop-in that always raises ``CryptoPayError``."""

    captured: list[dict] = []

    def __init__(self, *_a, **_kw) -> None:
        pass

    async def __aenter__(self) -> "_ErrorCryptoPay":
        return self

    async def __aexit__(self, *_exc) -> None:  # noqa: ANN001
        return None

    async def transfer(self, **kwargs) -> Transfer:
        _ErrorCryptoPay.captured.append(kwargs)
        raise CryptoPayError("Crypto Pay HTTP error: simulated upstream 500")


# ── T1 — silent admin self-payout ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_t1_non_digit_address_is_rejected_422(client, monkeypatch):
    """Schema-level guard: a wallet-style address (non-digit) is
    rejected with 422 before any treasury row is inserted.

    Pre-fix the validator only checked length, the handler then fell
    back to ``admin.tg_user_id`` and silently paid the admin.
    """
    admin_init, _, _ = await _make_admin(client, tg=8801)
    monkeypatch.setattr(app_settings, "cryptobot_token", "real-looking-token")

    resp = await client.post(
        "/api/admin/treasury/withdraw",
        json={
            "currency_code": "USDT",
            "amount": 1.0,
            # Classic TRC-20 USDT address shape — non-digit.
            "address": "T9yLAS" + "x" * 28,
            "confirm": True,
            "note": "should not pass",
        },
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 422, resp.text

    # No treasury row was inserted.
    async with async_session() as session:
        count = (await session.execute(select(func.count(TreasuryWithdrawal.id)))).scalar_one()
        assert count == 0


@pytest.mark.asyncio
async def test_t1_zero_and_negative_user_ids_rejected_422(client, monkeypatch):
    """A ``0`` or negative ``user_id`` is rejected at the schema."""
    admin_init, _, _ = await _make_admin(client, tg=8802)
    monkeypatch.setattr(app_settings, "cryptobot_token", "real-looking-token")

    for bad in ("0", "-1", "  ", ""):
        resp = await client.post(
            "/api/admin/treasury/withdraw",
            json={
                "currency_code": "USDT",
                "amount": 1.0,
                "address": bad,
                "confirm": True,
            },
            headers=with_totp(auth_headers(admin_init)),
        )
        assert resp.status_code == 422, (bad, resp.text)


@pytest.mark.asyncio
async def test_t1_user_id_actually_passed_to_cryptobot(client, monkeypatch):
    """T1 — the handler passes ``int(body.address)`` to
    ``cp.transfer``, NOT ``admin.tg_user_id``. Pre-fix any non-digit
    address silently rerouted the payout to the admin's own Telegram
    account.
    """
    admin_init, _, admin_tg = await _make_admin(client, tg=8803)
    monkeypatch.setattr(app_settings, "cryptobot_token", "real-looking-token")

    _CapturingCryptoPay.captured = []
    monkeypatch.setattr(treasury_router, "CryptoPay", _CapturingCryptoPay)

    async def _noop_lock(session, currency_id):  # noqa: ARG001
        return None

    async def _fake_accrued(session):  # noqa: ARG001
        async with async_session() as s:
            usdt = (await s.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
            return {usdt.id: Decimal("10")}

    async def _fake_withdrawn(session):  # noqa: ARG001
        return {}

    monkeypatch.setattr(treasury_router, "_lock_treasury", _noop_lock)
    monkeypatch.setattr(treasury_router, "_accrued_by_currency", _fake_accrued)
    monkeypatch.setattr(treasury_router, "_withdrawn_by_currency", _fake_withdrawn)

    target_user_id = "98765432"  # ≠ admin_tg
    assert int(target_user_id) != admin_tg, "test fixture must differ from admin"

    resp = await client.post(
        "/api/admin/treasury/withdraw",
        json={
            "currency_code": "USDT",
            "amount": 1.0,
            "address": target_user_id,
            "confirm": True,
            "note": "T1 regression",
        },
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text

    assert len(_CapturingCryptoPay.captured) == 1
    call = _CapturingCryptoPay.captured[0]
    assert call["user_id"] == int(target_user_id), (
        f"expected cp.transfer to be called with user_id={target_user_id}, "
        f"got {call['user_id']} (admin_tg={admin_tg})"
    )
    assert call["user_id"] != admin_tg
    assert call["asset"] == "USDT"
    # spend_id format ``treas:{row.id}`` is the CryptoBot idempotency key.
    assert call["spend_id"].startswith("treas:")


# ── T2 — three-phase commit ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_t2_happy_path_three_phase_commit(client, monkeypatch):
    """Audit T2 — the row lands ``sent`` with the right transfer_id,
    audit row written, balance accounting honours the Phase 1 commit.
    """
    admin_init, admin_id, _ = await _make_admin(client, tg=8901)
    monkeypatch.setattr(app_settings, "cryptobot_token", "real-looking-token")

    _CapturingCryptoPay.captured = []
    monkeypatch.setattr(treasury_router, "CryptoPay", _CapturingCryptoPay)

    # Seed enough commission accrual that the 1.0 USDT withdrawal fits.
    buyer = await _bootstrap(client, tg_user_id=8902, username="buyer")
    seller = await _bootstrap(client, tg_user_id=8903, username="seller")
    await _seed_completed_deal_with_commission(
        buyer_id=buyer, seller_id=seller, commission=Decimal("5.00")
    )

    resp = await client.post(
        "/api/admin/treasury/withdraw",
        json={
            "currency_code": "USDT",
            "amount": 1.0,
            "address": "55501234",
            "confirm": True,
            "note": "T2 happy",
        },
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "sent"
    assert body["cryptobot_transfer_id"] == "777001"

    async with async_session() as session:
        row = (
            await session.execute(
                select(TreasuryWithdrawal).order_by(TreasuryWithdrawal.id.desc()).limit(1)
            )
        ).scalar_one()
        assert row.status == "sent"
        assert row.cryptobot_transfer_id == "777001"
        assert row.address == "55501234"

        # Audit row written in Phase 3.
        audit = (
            await session.execute(
                select(AdminAuditLog)
                .where(AdminAuditLog.action == "treasury.withdraw")
                .order_by(AdminAuditLog.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        assert audit is not None
        assert audit.actor_id == admin_id
        assert audit.target_id == row.id
        assert audit.payload is not None
        assert audit.payload.get("cryptobot_transfer_id") == 777_001

    # spend_id is deterministic and tied to the row id.
    assert _CapturingCryptoPay.captured[0]["spend_id"] == f"treas:{row.id}"


@pytest.mark.asyncio
async def test_t2_cryptobot_failure_marks_failed_and_audits(client, monkeypatch):
    """Audit T2 — Phase 2 raises ``CryptoPayError`` → row reaches
    ``failed`` in Phase 3, ``treasury.withdraw_failed`` audit row
    written, 502 returned. The ``pending`` row that Phase 1 inserted
    is **not** orphaned.
    """
    admin_init, admin_id, _ = await _make_admin(client, tg=8911)
    monkeypatch.setattr(app_settings, "cryptobot_token", "real-looking-token")

    _ErrorCryptoPay.captured = []
    monkeypatch.setattr(treasury_router, "CryptoPay", _ErrorCryptoPay)

    buyer = await _bootstrap(client, tg_user_id=8912, username="buyer")
    seller = await _bootstrap(client, tg_user_id=8913, username="seller")
    await _seed_completed_deal_with_commission(
        buyer_id=buyer, seller_id=seller, commission=Decimal("5.00")
    )

    resp = await client.post(
        "/api/admin/treasury/withdraw",
        json={
            "currency_code": "USDT",
            "amount": 1.0,
            "address": "55501234",
            "confirm": True,
            "note": "T2 fail",
        },
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 502, resp.text

    async with async_session() as session:
        row = (
            await session.execute(
                select(TreasuryWithdrawal).order_by(TreasuryWithdrawal.id.desc()).limit(1)
            )
        ).scalar_one()
        assert row.status == "failed"
        assert "failed:" in (row.note or "")
        assert row.cryptobot_transfer_id is None

        audit = (
            await session.execute(
                select(AdminAuditLog)
                .where(AdminAuditLog.action == "treasury.withdraw_failed")
                .order_by(AdminAuditLog.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        assert audit is not None
        assert audit.actor_id == admin_id
        assert audit.payload is not None
        assert "error" in audit.payload


@pytest.mark.asyncio
async def test_t2_pending_row_counts_against_available(client, monkeypatch):
    """Audit T2 — once Phase 1 commits a ``pending`` row, the
    advisory lock is dropped. A second admin attempting another
    payout on the same currency sees ``pending`` counted in
    ``_OUTSTANDING_STATUSES`` and is rejected with 400 "недостаточно
    комиссии" — NOT queued behind the (now-released) advisory lock.

    Pre-fix the lock was held through the CryptoBot HTTP call, so the
    second admin would wait minutes on the advisory acquire while the
    first admin's request was in Phase 2. Post-fix the lock has been
    released by the Phase 1 commit, so the second admin gets a
    deterministic 400 quickly.

    We exercise this by:

    1. Inserting a ``pending`` row directly (representing first admin's
       Phase 1 commit) using the same currency.
    2. Verifying ``_withdrawn_by_currency`` includes the pending row,
       so the second admin's ``available`` calculation reflects it.
    3. Issuing the second admin's request and asserting 400.

    We do **not** exercise full async concurrency through ``httpx`` +
    ``ASGITransport`` because that test harness serialises requests
    on a shared client; the state-machine assertion above captures
    the bug-fix contract without the harness limitation.
    """
    admin_init, admin_id, _ = await _make_admin(client, tg=8921)
    monkeypatch.setattr(app_settings, "cryptobot_token", "real-looking-token")

    # Accrue exactly 1 USDT — first admin claims it, second admin
    # cannot find any ``available`` once the ``pending`` row is
    # counted against ``_OUTSTANDING_STATUSES``.
    buyer = await _bootstrap(client, tg_user_id=8923, username="buyer")
    seller = await _bootstrap(client, tg_user_id=8924, username="seller")
    await _seed_completed_deal_with_commission(
        buyer_id=buyer, seller_id=seller, commission=Decimal("1.00")
    )

    # Simulate first admin's Phase 1 commit: a ``pending`` row claiming
    # the full 1 USDT accrual.
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        pending_row = TreasuryWithdrawal(
            actor_id=admin_id,
            currency_id=usdt.id,
            amount=Decimal("1.00"),
            address="55501111",
            status="pending",
            note="simulated first-admin Phase 1",
        )
        session.add(pending_row)
        await session.commit()

        # ``_OUTSTANDING_STATUSES`` includes ``pending``, so the
        # row is counted against ``available`` immediately.
        withdrawn = await treasury_router._withdrawn_by_currency(session)
        assert withdrawn.get(usdt.id, Decimal(0)) == Decimal("1.00")

    # The second admin's request must be rejected at the
    # ``available`` guard, not queued on the advisory lock.
    resp = await client.post(
        "/api/admin/treasury/withdraw",
        json={
            "currency_code": "USDT",
            "amount": 1.0,
            "address": "55502222",
            "confirm": True,
            "note": "T2 concurrent second",
        },
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 400, resp.text
    assert "Недостаточно комиссии" in resp.text


@pytest.mark.asyncio
async def test_t2_advisory_lock_released_before_cryptobot_call(client, monkeypatch):
    """Audit T2 — direct contract check: the advisory lock is held
    only during Phase 1 (until the row is inserted + committed) and
    is dropped **before** ``CryptoPay.transfer`` is called.

    Pre-fix the lock was acquired before the ``pending`` insert and
    only released by the final ``commit()`` at the end of the
    handler, which sat after the CryptoBot HTTP roundtrip.
    """
    admin_init, _, _ = await _make_admin(client, tg=8931)
    monkeypatch.setattr(app_settings, "cryptobot_token", "real-looking-token")

    buyer = await _bootstrap(client, tg_user_id=8932, username="buyer")
    seller = await _bootstrap(client, tg_user_id=8933, username="seller")
    await _seed_completed_deal_with_commission(
        buyer_id=buyer, seller_id=seller, commission=Decimal("5.00")
    )

    # Snapshot the order of events: when ``CryptoPay.transfer`` is
    # called, the pending row must already be committed and visible
    # from an independent session — i.e. the Phase 1 ``commit()``
    # has run and dropped the advisory lock.
    pending_visible_during_phase2: list[bool] = []

    class _ObservingCryptoPay:
        def __init__(self, *_a, **_kw) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc) -> None:  # noqa: ANN001
            return None

        async def transfer(self, **kwargs):
            # Independent session checks the post-Phase-1 state.
            async with async_session() as observer:
                row = (
                    await observer.execute(
                        select(TreasuryWithdrawal).where(TreasuryWithdrawal.status == "pending")
                    )
                ).scalar_one_or_none()
                pending_visible_during_phase2.append(row is not None)
            return Transfer(
                transfer_id=555_555,
                user_id=kwargs["user_id"],
                asset=kwargs["asset"],
                amount=kwargs["amount"],
                status="completed",
                completed_at=None,
            )

    monkeypatch.setattr(treasury_router, "CryptoPay", _ObservingCryptoPay)

    resp = await client.post(
        "/api/admin/treasury/withdraw",
        json={
            "currency_code": "USDT",
            "amount": 1.0,
            "address": "55501234",
            "confirm": True,
            "note": "T2 lock-release",
        },
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text

    assert pending_visible_during_phase2 == [True], (
        "Phase 2 must observe the pending row from an independent "
        "session — the advisory lock + Phase 1 transaction must have "
        "released before CryptoPay.transfer was called."
    )
