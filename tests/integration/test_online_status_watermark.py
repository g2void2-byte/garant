"""R3 / H-8 — ``UserOut.online`` must be derived from ``last_login_at``.

The legacy serializer hard-coded ``online=True``, which made every
user listed in the search/profile UI look perpetually online. The fix
(landed in commit ``cda5fdb``) reads ``last_login_at`` and compares it
to a 5-minute watermark. These tests pin the contract so a future
refactor can't silently revert.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.app.db import async_session
from backend.app.models import User
from backend.app.schemas import UserOut
from backend.app.serializers import _ONLINE_THRESHOLD, user_to_out
from backend.app.time_utils import utcnow
from tests.helpers import auth_headers, signed_init_data


def test_online_threshold_is_five_minutes():
    """A small property test on the constant so any change shows up in
    the diff (we ship the threshold as part of the contract)."""
    assert _ONLINE_THRESHOLD == timedelta(minutes=5)


def _fresh_user(**overrides) -> User:
    """Build an in-memory ``User`` with the columns ``user_to_out``
    reads non-defensively populated. The ORM applies these defaults
    on flush; tests that don't go through the DB have to set them
    explicitly."""
    base = {
        "id": 12000,
        "tg_user_id": 12000,
        "username": "user",
        "display_name": "User",
        "good": 0,
        "bad": 0,
        "deals_total": 0,
        "description": "",
        "is_admin": False,
        "is_arbiter": False,
        "is_vip": False,
        "is_banned": False,
        "is_frozen": False,
        "is_anonymous_deals": False,
        "is_hidden_profile": False,
        "dm_deals": True,
        "dm_deposits": True,
        "dm_system": True,
        "forums": [],
    }
    base.update(overrides)
    return User(**base)


def test_user_to_out_marks_recently_seen_as_online():
    """A user whose ``last_login_at`` is 30 seconds old reads as
    online."""
    u = _fresh_user(
        tg_user_id=12001,
        username="recent",
        display_name="Recent",
        last_login_at=datetime.now(UTC) - timedelta(seconds=30),
    )
    out: UserOut = user_to_out(u)
    assert out.online is True


def test_user_to_out_marks_long_idle_as_offline():
    """A user whose ``last_login_at`` is 1 hour old reads as offline."""
    u = _fresh_user(
        tg_user_id=12002,
        username="idle",
        display_name="Idle",
        last_login_at=datetime.now(UTC) - timedelta(hours=1),
    )
    out = user_to_out(u)
    assert out.online is False


def test_user_to_out_marks_never_seen_as_offline():
    """A freshly-created row with ``last_login_at=None`` is offline."""
    u = _fresh_user(
        tg_user_id=12003,
        username="cold",
        display_name="Cold",
        last_login_at=None,
    )
    out = user_to_out(u)
    assert out.online is False


def test_user_to_out_threshold_boundary_within_window():
    """Just inside the 5-minute window → still online."""
    u = _fresh_user(
        tg_user_id=12004,
        username="edge",
        display_name="Edge",
        last_login_at=datetime.now(UTC) - timedelta(minutes=4, seconds=55),
    )
    assert user_to_out(u).online is True


def test_user_to_out_threshold_boundary_outside_window():
    """Just outside the 5-minute window → offline."""
    u = _fresh_user(
        tg_user_id=12005,
        username="edge2",
        display_name="Edge2",
        last_login_at=datetime.now(UTC) - timedelta(minutes=5, seconds=1),
    )
    assert user_to_out(u).online is False


# ── End-to-end through /api/me ────────────────────────────────────────────


async def test_me_endpoint_reports_online_after_call(client):
    """A user that just hit ``/api/me`` should have ``last_login_at``
    stamped to ``utcnow()`` and consequently report ``online=true``."""
    init = signed_init_data(12010, "live_user")
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["online"] is True


async def test_users_search_reports_offline_for_stale_login(client):
    """An old user whose ``last_login_at`` is far in the past reports
    ``online=false`` in the public ``/api/users`` list."""
    # Bootstrap a caller (creates a row, stamps last_login_at).
    caller_init = signed_init_data(12011, "caller_o2")
    await client.get("/api/me", headers=auth_headers(caller_init))

    # Manufacture a "stale" user directly in DB. ``last_login_at`` is
    # TIMESTAMP WITHOUT TIME ZONE on the column, so we use the project's
    # ``utcnow`` helper (returns a naive datetime) rather than a
    # tz-aware ``datetime.now(timezone.utc)``.
    async with async_session() as session:
        u = User(
            tg_user_id=12012,
            username="stale_user",
            display_name="Stale",
            last_login_at=utcnow() - timedelta(days=2),
        )
        session.add(u)
        await session.commit()

    resp = await client.get(
        "/api/users",
        params={"q": "stale_user"},
        headers=auth_headers(caller_init),
    )
    assert resp.status_code == 200, resp.text
    matched = next(item for item in resp.json() if item["username"] == "stale_user")
    assert matched["online"] is False
