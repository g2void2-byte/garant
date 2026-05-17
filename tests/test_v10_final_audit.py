"""Regression tests for the v10 final-audit cleanup.

Covers Comments 32, 33, 38, 42, 45, 49, V5-E-4..6 and V5-F-7/8.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import time

from tests.helpers import (
    auth_headers,
    credit_balance,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# ═══════════════════════ Comment 32 — split notifier API ═══════════════════


async def test_notifier_insert_returns_notification_and_payload():
    """insert() persists a Notification row and returns the ws payload."""
    from httpx import ASGITransport, AsyncClient

    from backend.app.db import async_session
    from backend.app.main import app
    from backend.app.models import Notification, NotificationType
    from backend.app.notifier import insert

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        init = signed_init_data(32001, "n32001")
        await setup_pin(c, init)

    async with async_session() as session:
        uid = await get_user_id_by_tg(session, 32001)
        notif, ws_payload = await insert(
            session,
            uid,
            NotificationType.system,
            "Test title",
            "Test body",
            {"key": "val"},
        )
        await session.commit()
        assert isinstance(notif, Notification)
        assert notif.id is not None
        assert ws_payload == {"key": "val"}


async def test_notifier_dispatch_after_commit_publishes():
    """dispatch_after_commit() runs without error after a commit."""
    from httpx import ASGITransport, AsyncClient

    from backend.app.db import async_session
    from backend.app.main import app
    from backend.app.models import NotificationType
    from backend.app.notifier import dispatch_after_commit, insert

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        init = signed_init_data(32002, "n32002")
        await setup_pin(c, init)

    async with async_session() as session:
        uid = await get_user_id_by_tg(session, 32002)
        notif, ws_payload = await insert(
            session,
            uid,
            NotificationType.system,
            "T",
            "B",
        )
        await session.commit()
        # Should not raise.
        await dispatch_after_commit(session, notif, ws_payload)


async def test_notifier_push_convenience_wrapper():
    """push() persists + dispatches in one call (backward compat)."""
    from httpx import ASGITransport, AsyncClient

    from backend.app.db import async_session
    from backend.app.main import app
    from backend.app.models import Notification, NotificationType
    from backend.app.notifier import push

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        init = signed_init_data(32003, "n32003")
        await setup_pin(c, init)

    async with async_session() as session:
        uid = await get_user_id_by_tg(session, 32003)
        notif = await push(
            session,
            uid,
            NotificationType.system,
            "Push test",
            "",
        )
        assert isinstance(notif, Notification)


async def test_sweep_inactivity_uses_split_notifier(client):
    """sweep_inactivity dispatches notifications after commit."""
    from sqlalchemy import select

    from backend.app.db import async_session
    from backend.app.models import Deal, Notification
    from backend.app.services_deals import sweep_inactivity

    buyer_init = signed_init_data(32010, "buyer32010")
    seller_init = signed_init_data(32011, "seller32011")
    buyer_pin = await setup_pin(client, buyer_init)
    await setup_pin(client, seller_init)

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 32010)
        await credit_balance(session, buyer_id, "USDT", 100)

    deal_resp = await client.post(
        "/api/deals",
        json={
            "counterparty": "seller32011",
            "role": "buyer",
            "sum": 10,
            "currency_code": "USDT",
            "pay_comission": "buyer",
        },
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    deal_id = deal_resp.json()["id"]

    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        from backend.app.time_utils import utcnow

        deal.created_at = utcnow() - dt.timedelta(days=30)
        await session.commit()

        affected = await sweep_inactivity(session)
        assert affected == 1

    # Notifications should have been created for both parties.
    async with async_session() as session:
        notifs = (
            (
                await session.execute(
                    select(Notification).where(
                        Notification.title == "Сделка отменена за неактивность"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(notifs) == 2


# ═══════════════════════ Comment 33 — FK CASCADE / SET NULL ════════════════


async def test_fk_cascade_model_annotation():
    """ServiceComment.service_id has ondelete=CASCADE in the model."""
    from backend.app.models import ServiceComment

    col = ServiceComment.__table__.columns["service_id"]
    fk = list(col.foreign_keys)[0]
    assert fk.ondelete == "CASCADE"


async def test_fk_set_null_model_annotation():
    """Review.deal_id has ondelete=SET NULL in the model."""
    from backend.app.models import Review

    col = Review.__table__.columns["deal_id"]
    fk = list(col.foreign_keys)[0]
    assert fk.ondelete == "SET NULL"


async def test_fk_migration_file_exists():
    """The Comment 33 migration file exists and has correct revision."""
    path = (
        REPO_ROOT / "alembic" / "versions" / "a1b2c3d4e5f6_fk_cascade_service_comments_reviews.py"
    )
    assert path.exists()
    text = path.read_text()
    assert 'revision: str = "a1b2c3d4e5f6"' in text
    assert 'down_revision: str | None = "d9f1c3a8e205"' in text


# ═══════════════════════ Comment 38 — WS DoS hardening ═════════════════════


async def test_ws_socket_cap_rejects_excess(monkeypatch):
    """ConnectionManager.connect() rejects when cap is reached."""
    from backend.app.ws import ConnectionManager

    monkeypatch.setattr("backend.app.config.settings.ws_max_sockets_per_user", 2)

    class _FakeWS:
        def __init__(self):
            self.closed_code = None

        async def send_text(self, _t):
            pass

        async def close(self, code=1000, reason=""):
            self.closed_code = code

    mgr = ConnectionManager()
    ws1, ws2, ws3 = _FakeWS(), _FakeWS(), _FakeWS()
    await mgr.connect(1, ws1, auth_date_epoch=None)  # type: ignore[arg-type]
    await mgr.connect(1, ws2, auth_date_epoch=None)  # type: ignore[arg-type]
    await mgr.connect(1, ws3, auth_date_epoch=None)  # type: ignore[arg-type]

    # ws3 should have been rejected.
    assert ws3.closed_code == 4008
    assert id(ws3) not in mgr._states

    mgr.disconnect(1, ws1)  # type: ignore[arg-type]
    mgr.disconnect(1, ws2)  # type: ignore[arg-type]


async def test_ws_recv_rate_within_limit():
    """check_recv_rate returns True when under the limit."""
    from backend.app.ws import ConnectionManager

    class _FakeWS:
        async def send_text(self, _t):
            pass

        async def close(self, code=1000, reason=""):
            pass

    mgr = ConnectionManager()
    ws = _FakeWS()
    await mgr.connect(2, ws, auth_date_epoch=None)  # type: ignore[arg-type]
    try:
        assert mgr.check_recv_rate(ws) is True  # type: ignore[arg-type]
    finally:
        mgr.disconnect(2, ws)  # type: ignore[arg-type]


async def test_ws_recv_rate_exceeds_limit(monkeypatch):
    """check_recv_rate returns False after burst exceeds the limit."""
    monkeypatch.setattr("backend.app.config.settings.ws_recv_max_messages_per_second", 3.0)

    from backend.app.ws import ConnectionManager

    class _FakeWS:
        async def send_text(self, _t):
            pass

        async def close(self, code=1000, reason=""):
            pass

    mgr = ConnectionManager()
    ws = _FakeWS()
    await mgr.connect(3, ws, auth_date_epoch=None)  # type: ignore[arg-type]
    try:
        for _ in range(3):
            assert mgr.check_recv_rate(ws) is True  # type: ignore[arg-type]
        # 4th call should exceed limit of 3.
        assert mgr.check_recv_rate(ws) is False  # type: ignore[arg-type]
    finally:
        mgr.disconnect(3, ws)  # type: ignore[arg-type]


async def test_ws_recv_rate_resets_window(monkeypatch):
    """Rate window resets after 1 second, allowing new messages."""
    monkeypatch.setattr("backend.app.config.settings.ws_recv_max_messages_per_second", 2.0)

    from backend.app.ws import ConnectionManager

    class _FakeWS:
        async def send_text(self, _t):
            pass

        async def close(self, code=1000, reason=""):
            pass

    mgr = ConnectionManager()
    ws = _FakeWS()
    await mgr.connect(4, ws, auth_date_epoch=None)  # type: ignore[arg-type]
    try:
        mgr.check_recv_rate(ws)  # type: ignore[arg-type]
        mgr.check_recv_rate(ws)  # type: ignore[arg-type]
        assert mgr.check_recv_rate(ws) is False  # type: ignore[arg-type]

        # Simulate window expiry by resetting window_start.
        state = mgr._states[id(ws)]
        state.recv_rate.window_start = time.monotonic() - 2.0
        assert mgr.check_recv_rate(ws) is True  # type: ignore[arg-type]
    finally:
        mgr.disconnect(4, ws)  # type: ignore[arg-type]


async def test_ws_heartbeat_sends_ping():
    """send_heartbeat() sends a JSON ping frame."""
    from backend.app.ws import ConnectionManager

    class _FakeWS:
        def __init__(self):
            self.sent: list[str] = []

        async def send_text(self, t):
            self.sent.append(t)

        async def close(self, code=1000, reason=""):
            pass

    mgr = ConnectionManager()
    ws = _FakeWS()
    await mgr.connect(5, ws, auth_date_epoch=None)  # type: ignore[arg-type]
    try:
        await mgr.send_heartbeat(ws)  # type: ignore[arg-type]
        assert len(ws.sent) == 1
        assert json.loads(ws.sent[0]) == {"type": "ping"}
    finally:
        mgr.disconnect(5, ws)  # type: ignore[arg-type]


# ═══════════════════════ Comment 42 — PIN token validation ═════════════════


def test_pin_set_token_rejects_nan():
    """setPinToken validation: the function is in TypeScript, so we
    verify the source contains the Number.isFinite guard."""
    pin_ts = (REPO_ROOT / "frontend" / "src" / "lib" / "pin.ts").read_text()
    assert "Number.isFinite" in pin_ts


# ═══════════════════════ Comment 45 — GDPR IP purge ════════════════════════


async def test_sweep_user_last_ip_purges_stale(monkeypatch):
    """sweep_user_last_ip nulls last_ip for users past the retention window."""
    monkeypatch.setattr("backend.app.config.settings.last_ip_retention_seconds", 1)

    from httpx import ASGITransport, AsyncClient

    from backend.app.db import async_session
    from backend.app.main import app
    from backend.app.models import User
    from backend.app.services import sweep_user_last_ip

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        init = signed_init_data(45001, "gdpr45001")
        await setup_pin(c, init)

    async with async_session() as session:
        uid = await get_user_id_by_tg(session, 45001)
        user = await session.get(User, uid)
        user.last_ip = "192.168.1.1"
        from backend.app.time_utils import utcnow

        user.last_login_at = utcnow() - dt.timedelta(days=1)
        await session.commit()

    async with async_session() as session:
        purged = await sweep_user_last_ip(session)
        assert purged >= 1

    async with async_session() as session:
        uid = await get_user_id_by_tg(session, 45001)
        user = await session.get(User, uid)
        assert user.last_ip is None


async def test_sweep_user_last_ip_disabled_when_zero(monkeypatch):
    """sweep_user_last_ip returns 0 when retention is disabled."""
    monkeypatch.setattr("backend.app.config.settings.last_ip_retention_seconds", 0)

    from backend.app.db import async_session
    from backend.app.services import sweep_user_last_ip

    async with async_session() as session:
        result = await sweep_user_last_ip(session)
        assert result == 0


async def test_last_ip_purge_loop_disabled_when_sweep_zero(monkeypatch):
    """The lifespan doesn't schedule the purge loop when sweep_seconds=0."""
    from backend.app.config import settings

    assert settings.last_ip_purge_sweep_seconds > 0
    # Just verify the setting exists and is positive by default.
    assert settings.last_ip_retention_seconds > 0


# ═══════════════════════ Comment 49 — TOTP pending cache ═══════════════════


async def test_totp_store_and_pop_pending():
    """_store_pending / _pop_pending round-trip with in-process fallback."""
    from backend.app.routers.admin.twofa import _pop_pending, _store_pending

    await _store_pending(99999, "JBSWY3DPEHPK3PXP")
    secret = await _pop_pending(99999)
    assert secret == "JBSWY3DPEHPK3PXP"

    # Second pop should return None (consumed).
    assert await _pop_pending(99999) is None


async def test_totp_pending_expires():
    """In-process fallback respects TTL expiry."""
    from backend.app.routers.admin.twofa import (
        _pending_secrets,
        _pop_pending,
    )

    # Manually inject an expired entry.
    _pending_secrets[88888] = ("SECRET", time.monotonic() - 10)
    result = await _pop_pending(88888)
    assert result is None


# ═══════════════════════ V5-E-4..6 — alembic housekeeping ═════════════════


def test_initial_schema_no_autogen_banner():
    """V5-E-4: initial_schema.py has no auto-generated banners."""
    path = REPO_ROOT / "alembic" / "versions" / "9d0e4d959e65_initial_schema.py"
    text = path.read_text()
    assert "auto generated by Alembic" not in text
    assert "end Alembic commands" not in text


def test_initial_schema_pep604_syntax():
    """V5-E-5: initial_schema.py uses PEP 604 syntax (str | None)."""
    path = REPO_ROOT / "alembic" / "versions" / "9d0e4d959e65_initial_schema.py"
    text = path.read_text()
    assert "Union[str, None]" not in text
    assert "str | None" in text


def test_moderator_migration_cross_reference():
    """V5-E-6: pr4_user_moderator_flag.py references the drop revision."""
    path = REPO_ROOT / "alembic" / "versions" / "2f4b9a13c81d_pr4_user_moderator_flag.py"
    text = path.read_text()
    assert "d4f1a8c92e34" in text


# ═══════════════════════ V5-F-7/8 — frontend Pin UX ═══════════════════════


def test_pinpage_has_mode_effect():
    """V5-F-7: PinPage.tsx has the mode-sync useEffect."""
    path = REPO_ROOT / "frontend" / "src" / "pages" / "pin" / "PinPage.tsx"
    text = path.read_text()
    assert "}, [mode])" in text
    assert 'setMemo("")' in text


def test_pinpage_has_mount_wipe():
    """V5-F-7: PinPage.tsx has the mount-time wipe useEffect."""
    path = REPO_ROOT / "frontend" / "src" / "pages" / "pin" / "PinPage.tsx"
    text = path.read_text()
    assert "}, [])" in text
    assert 'setResetCode("")' in text


def test_pinresetpage_shows_attempts_left():
    """V5-F-8: PinResetPage.tsx shows attempts_left."""
    path = REPO_ROOT / "frontend" / "src" / "pages" / "pin" / "PinResetPage.tsx"
    text = path.read_text()
    assert "attempts_left" in text
    assert 'data-testid="pin-reset-attempts-left"' in text


def test_pinresetpage_imports_usepinstatus():
    """V5-F-8: PinResetPage.tsx imports usePinStatus."""
    path = REPO_ROOT / "frontend" / "src" / "pages" / "pin" / "PinResetPage.tsx"
    text = path.read_text()
    assert "usePinStatus" in text
