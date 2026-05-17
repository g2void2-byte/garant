"""V9 — second Medium-severity batch regression suite.

Maps 1:1 to ``audit-status-v9.md §2.A`` after PR #91 landed:

* **Comment 39** — ``notifier.push`` caps the persisted ``payload`` at
  4 KB and drops oversize blobs (still emitting the row + WS event so
  the recipient knows *something* happened).
* **Comment 43** — ``services_account._purge_expired`` deletes every
  expired/consumed code, not just the 24-hour-old subset; the new
  ``_generate_unique_code`` helper retries when it would otherwise
  collide with a live row.
* **Comment 44** — ``PATCH /api/me`` with a ``forums`` replace returns
  the post-commit forum list (no stale ``Forum`` rows surviving the
  selectin cache).
* **Comment 48** — ``POST /api/admin/treasury/withdraw`` rejects with
  HTTP 503 when ``cryptobot_token`` is unset/placeholder, *before*
  inserting any ``TreasuryWithdrawal`` row.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from backend.app.config import settings as app_settings
from backend.app.db import async_session
from backend.app.models import (
    AccountTransferCode,
    Currency,
    Notification,
    NotificationType,
    TreasuryWithdrawal,
    User,
)
from backend.app.notifier import NOTIFICATION_PAYLOAD_MAX_BYTES, push
from backend.app.services_account import (
    _generate_unique_code,
    _hash_code,
    _purge_expired,
    issue_code,
)
from backend.app.time_utils import utcnow
from tests.helpers import (
    auth_headers,
    signed_init_data,
    with_totp,
)


async def _bootstrap(client, *, tg_user_id: int, username: str) -> int:
    init = signed_init_data(tg_user_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _make_admin(client, tg: int) -> tuple[str, int]:
    init = signed_init_data(tg, f"admin{tg}")
    uid = await _bootstrap(client, tg_user_id=tg, username=f"admin{tg}")
    async with async_session() as session:
        u = await session.get(User, uid)
        u.is_admin = True
        await session.commit()
    return init, uid


# ── Comment 39 — payload cap on notifier.push ───────────────────────────


@pytest.mark.asyncio
async def test_notifier_push_drops_oversize_payload(client, monkeypatch, caplog):
    """A payload that serialises past 4 KB lands as ``NULL`` on the
    ``notifications`` row and as ``None`` on the WS event — the
    notification itself is still delivered so the recipient sees the
    title/body, just without the corrupt blob."""

    bob_id = await _bootstrap(client, tg_user_id=9101, username="payload_bob")

    big_value = "x" * (NOTIFICATION_PAYLOAD_MAX_BYTES + 200)
    oversize = {"k": big_value, "deal_id": 42}

    publish_calls: list[dict] = []

    async def _capture_publish(uid, data):  # noqa: ARG001
        publish_calls.append(data)

    monkeypatch.setattr("backend.app.notifier.manager.publish", _capture_publish)

    async with async_session() as session:
        with caplog.at_level(logging.WARNING, logger="backend.app.notifier"):
            notif = await push(
                session,
                recipient_id=bob_id,
                type_=NotificationType.system,
                title="System",
                body="see payload",
                payload=oversize,
            )
        await session.commit()
        notif_id = notif.id

    async with async_session() as session:
        row = (
            await session.execute(select(Notification).where(Notification.id == notif_id))
        ).scalar_one()
        assert row.payload is None, "row.payload must be NULLed when too large"
        assert row.title == "System"
        assert row.body == "see payload"

    assert publish_calls, "WS publish must still fire so the client gets notified"
    ws_payload = publish_calls[-1]["data"]["payload"]
    assert ws_payload is None, "WS payload must be dropped, not echoed raw"
    assert any(
        "exceeds" in r.message and "dropping" in r.message
        for r in caplog.records
        if r.name == "backend.app.notifier"
    ), "must log a warning when dropping oversize payloads"


@pytest.mark.asyncio
async def test_notifier_push_keeps_small_payload(client, monkeypatch):
    """Sanity-check that the cap doesn't accidentally drop normal-sized
    payloads (the production fan-out is heavy and a false-positive cap
    would break every deal notification)."""

    alice_id = await _bootstrap(client, tg_user_id=9102, username="payload_alice")
    small = {"deal_id": 7, "amount": "1.50"}

    publish_calls: list[dict] = []

    async def _capture_publish(uid, data):  # noqa: ARG001
        publish_calls.append(data)

    monkeypatch.setattr("backend.app.notifier.manager.publish", _capture_publish)

    async with async_session() as session:
        notif = await push(
            session,
            recipient_id=alice_id,
            type_=NotificationType.deals,
            title="Deal updated",
            body="state=funded",
            payload=small,
        )
        await session.commit()
        notif_id = notif.id

    async with async_session() as session:
        row = (
            await session.execute(select(Notification).where(Notification.id == notif_id))
        ).scalar_one()
        # V11-M-10 — ``Notification.payload`` is now a JSONB column
        # mapped to ``dict | None``; assert structural equality rather
        # than substring matching on a JSON string.
        assert row.payload == small

    assert publish_calls
    assert publish_calls[-1]["data"]["payload"] == small


# ── Comment 43 — _purge_expired + _generate_unique_code ─────────────────


@pytest.mark.asyncio
async def test_purge_expired_clears_every_dead_row(client):
    """Pre-fix ``_purge_expired`` only touched rows with
    ``created_at < now - 1 day``, so a freshly-expired code (TTL is
    5 min by default) sat in the table for the rest of the day. The
    new version drops *all* expired / consumed rows on every call."""

    eve_id = await _bootstrap(client, tg_user_id=9201, username="purge_eve")

    async with async_session() as session:
        # Three expired rows — all created seconds ago, all already
        # past ``expires_at``. The old guard would have kept them.
        for n in range(3):
            session.add(
                AccountTransferCode(
                    source_user_id=eve_id,
                    code_hash=_hash_code(f"00000{n}"),
                    expires_at=utcnow() - timedelta(seconds=10),
                )
            )
        # One consumed-but-not-yet-expired row (e.g., user just
        # confirmed). Same logic — keep it around forever helps nobody.
        session.add(
            AccountTransferCode(
                source_user_id=eve_id,
                code_hash=_hash_code("111111"),
                expires_at=utcnow() + timedelta(minutes=5),
                consumed_at=utcnow(),
            )
        )
        # One still-live row that must NOT be purged.
        session.add(
            AccountTransferCode(
                source_user_id=eve_id,
                code_hash=_hash_code("222222"),
                expires_at=utcnow() + timedelta(minutes=5),
            )
        )
        await session.commit()

        await _purge_expired(session)
        await session.commit()

        total = (
            await session.execute(
                select(func.count(AccountTransferCode.id)).where(
                    AccountTransferCode.source_user_id == eve_id
                )
            )
        ).scalar_one()
        assert total == 1, "only the still-live row should survive _purge_expired"


@pytest.mark.asyncio
async def test_generate_unique_code_avoids_active_hash_collision(client, monkeypatch):
    """``_generate_unique_code`` walks the digit space until it finds
    a hash that isn't already attached to a live row — without this
    guard the audit's "6-digit codes, 10⁶ buckets" warning would let
    ``issue_code`` re-issue the same code to two different users."""

    user_a_id = await _bootstrap(client, tg_user_id=9301, username="collide_a")
    user_b_id = await _bootstrap(client, tg_user_id=9302, username="collide_b")

    async with async_session() as session:
        user_a = await session.get(User, user_a_id)
        first_code, _ = await issue_code(session, user_a)

    # Force the first generated digit-string back into the candidate
    # pool so the helper has to retry. The second draw is unique.
    calls = {"n": 0}

    def _draws(_charset):
        calls["n"] += 1
        # First six characters reproduce ``first_code``; everything
        # afterwards yields '7' so the loop terminates with a fresh
        # unique value.
        if calls["n"] <= 6:
            return first_code[calls["n"] - 1]
        return "7"

    monkeypatch.setattr("backend.app.services_account.secrets.choice", _draws)

    async with async_session() as session:
        user_b = await session.get(User, user_b_id)
        second_code = await _generate_unique_code(session)
        assert second_code != first_code, "must not collide with an active hash"
        assert len(second_code) == 6
        assert calls["n"] >= 7, "should have re-drawn after the first 6-digit collision"
        # Persist it under user_b so the test mirrors a real ``issue_code`` flow.
        session.add(
            AccountTransferCode(
                source_user_id=user_b.id,
                code_hash=_hash_code(second_code),
                expires_at=utcnow() + timedelta(minutes=5),
            )
        )
        await session.commit()


# ── Comment 44 — session.refresh(forums) after full-replace ─────────────


@pytest.mark.asyncio
async def test_patch_me_forums_replace_returns_post_commit_state(client):
    """``PATCH /api/me`` replaces the forum collection wholesale —
    delete-then-add-in-one-transaction. Without an explicit
    ``session.refresh(user, attribute_names=["forums"])`` the
    eager-loaded relationship can still echo the *old* rows back to
    the client (or worse, mix old + new ids). Verify the response
    matches the requested set exactly."""

    init = signed_init_data(9401, "forum_pat")
    await _bootstrap(client, tg_user_id=9401, username="forum_pat")

    # Seed with two initial forums.
    seed = await client.patch(
        "/api/me",
        json={
            "forums": [
                {"name": "Old1", "url": "https://forum-old-1.example.com/"},
                {"name": "Old2", "url": "https://forum-old-2.example.com/"},
            ]
        },
        headers=auth_headers(init),
    )
    assert seed.status_code == 200, seed.text
    seeded_urls = {f["url"] for f in seed.json()["forums"]}
    assert seeded_urls == {
        "https://forum-old-1.example.com/",
        "https://forum-old-2.example.com/",
    }

    # Wholesale replace.
    replaced = await client.patch(
        "/api/me",
        json={
            "forums": [
                {"name": "New1", "url": "https://t.me/forum_new_1"},
                {"name": "New2", "url": "https://forum-new-2.example.com/"},
                {"name": "New3", "url": "https://forum-new-3.example.com/"},
            ]
        },
        headers=auth_headers(init),
    )
    assert replaced.status_code == 200, replaced.text
    new_urls = {f["url"] for f in replaced.json()["forums"]}
    assert new_urls == {
        "https://t.me/forum_new_1",
        "https://forum-new-2.example.com/",
        "https://forum-new-3.example.com/",
    }
    # No old URL must leak through.
    assert "https://forum-old-1.example.com/" not in new_urls
    assert "https://forum-old-2.example.com/" not in new_urls

    # A follow-up GET must see the same post-commit state.
    fetched = await client.get("/api/me", headers=auth_headers(init))
    assert fetched.status_code == 200, fetched.text
    fetched_urls = {f["url"] for f in fetched.json()["forums"]}
    assert fetched_urls == new_urls


# ── Comment 48 — treasury_withdraw 503 when CryptoBot token missing ─────


@pytest.mark.asyncio
async def test_treasury_withdraw_503_when_cryptobot_token_empty(client, monkeypatch):
    """An admin who fires ``/api/admin/treasury/withdraw`` against an
    unconfigured CryptoBot must get a loud HTTP 503 — *before* a
    ``TreasuryWithdrawal`` row is inserted. Pre-fix the row was
    silently created with ``status="sent"`` and zero transfer id, so
    the accounting ledger believed a payout had happened.

    Covers both the empty-string case (uninitialised env) and the
    well-known ``000…`` placeholder we ship in conftest as a sentinel
    for unconfigured environments."""

    admin_init, _ = await _make_admin(client, tg=9501)

    async def _withdraw(token_value: str) -> int:
        monkeypatch.setattr(app_settings, "cryptobot_token", token_value)
        resp = await client.post(
            "/api/admin/treasury/withdraw",
            json={
                "currency_code": "USDT",
                "amount": 1.0,
                "address": "T" + "x" * 33,
                "confirm": True,
                "note": "test",
            },
            headers=with_totp(auth_headers(admin_init)),
        )
        return resp.status_code

    assert await _withdraw("") == 503
    assert await _withdraw("000-placeholder") == 503

    async with async_session() as session:
        count = (await session.execute(select(func.count(TreasuryWithdrawal.id)))).scalar_one()
        assert count == 0, "no TreasuryWithdrawal row may exist after a 503 rejection"


@pytest.mark.asyncio
async def test_treasury_withdraw_proceeds_when_token_configured(client, monkeypatch):
    """Mirror of the negative test — with a non-placeholder token the
    handler reaches the CryptoBot transfer call. Stub the transfer so
    no network IO leaks out of the test process, then assert the row
    lands as ``status="sent"``."""

    admin_init, _ = await _make_admin(client, tg=9502)

    monkeypatch.setattr(app_settings, "cryptobot_token", "real-looking-token")

    class _FakeTransfer:
        transfer_id = 4242

    class _FakeCryptoPay:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def transfer(self, **_kw):
            return _FakeTransfer()

    import backend.app.routers.admin.treasury as treasury_router

    monkeypatch.setattr(treasury_router, "CryptoPay", _FakeCryptoPay)

    # Avoid hitting the per-currency advisory lock with a real
    # connection — the test PG has it but a no-op keeps the assertion
    # focused on the new 503 branch.
    async def _noop_lock(session, currency_id):  # noqa: ARG001
        return None

    monkeypatch.setattr(treasury_router, "_lock_treasury", _noop_lock)

    # Pre-seed accrual so ``available`` is positive (the handler
    # checks ``accrued − withdrawn ≥ amount`` before transferring).
    async def _fake_accrued(session):  # noqa: ARG001
        async with async_session() as s:
            usdt = (await s.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
            return {usdt.id: Decimal("10")}

    async def _fake_withdrawn(session):  # noqa: ARG001
        return {}

    monkeypatch.setattr(treasury_router, "_accrued_by_currency", _fake_accrued)
    monkeypatch.setattr(treasury_router, "_withdrawn_by_currency", _fake_withdrawn)

    resp = await client.post(
        "/api/admin/treasury/withdraw",
        json={
            "currency_code": "USDT",
            "amount": 1.0,
            "address": "T" + "x" * 33,
            "confirm": True,
            "note": "smoke",
        },
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text

    async with async_session() as session:
        row = (
            await session.execute(
                select(TreasuryWithdrawal).order_by(TreasuryWithdrawal.id.desc()).limit(1)
            )
        ).scalar_one()
        assert row.status == "sent"
        assert row.cryptobot_transfer_id == "4242"


# Silence unused-import warning — keep ``asyncio``/``AsyncMock`` in the
# module so future fixtures can reuse the imports without re-adding.
_ = (asyncio, AsyncMock)
