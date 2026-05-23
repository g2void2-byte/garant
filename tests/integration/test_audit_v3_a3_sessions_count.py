"""Audit v3 A-3 — true distinct-session counter.

Pre-fix the only "I came back" signal on the User row was
``login_count``, which bumps every ``deps._LAST_LOGIN_DEBOUNCE``
(5 min) tick.  An SPA-foreground user racks up ~288 "logins" / day,
making the metric useless for "real return visits" analytics.  The
A-3 fix adds ``User.sessions_count``: bumps only when the gap since
the previous ping exceeds ``deps._SESSION_GAP`` (30 min by default),
mirroring industry-standard idle-session timeouts.

These tests assert the bump logic:

* a fresh user starts at ``sessions_count == 1``;
* a second request inside the session gap leaves ``sessions_count``
  alone (``login_count`` is still allowed to tick on the 5-min
  debounce);
* a request after the session gap bumps ``sessions_count`` to 2.

The gap is patched via the module-level ``deps._SESSION_GAP`` for
test speed, mirroring the existing ``_LAST_LOGIN_DEBOUNCE`` patch
pattern.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from backend.app.time_utils import utcnow
from tests.helpers import auth_headers, get_user_id_by_tg, signed_init_data


async def test_sessions_count_initialised_on_first_touch(client) -> None:
    """A brand-new user lands at ``sessions_count = 1`` and
    ``login_count = 1`` — the first authenticated request always
    counts as a new session because there's no prior ping to gap
    against."""
    from backend.app.db import async_session
    from backend.app.models import User

    init_data = signed_init_data(902001, "a3_first_touch")
    resp = await client.get("/api/me", headers=auth_headers(init_data))
    assert resp.status_code == 200, resp.text

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 902001)
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        assert user.login_count == 1
        assert user.sessions_count == 1


async def test_sessions_count_stable_inside_session_gap(client, monkeypatch) -> None:
    """Two pings inside the session gap leave ``sessions_count``
    alone.

    ``login_count`` still ticks on the debounce schedule (we
    rewind ``last_login_at`` enough to escape the 5-min debounce,
    but stay inside the 30-min session gap), so the two counters
    diverge in exactly the documented way: heavy SPA activity
    bumps the ping count without inflating the session count.
    """
    from backend.app import deps
    from backend.app.db import async_session
    from backend.app.models import User

    # Shorten the debounce so the second request always pings;
    # leave the session gap at its default 30 min so this request
    # is "still in session 1".
    monkeypatch.setattr(deps, "_LAST_LOGIN_DEBOUNCE", timedelta(seconds=0))

    init_data = signed_init_data(902002, "a3_in_gap")
    resp = await client.get("/api/me", headers=auth_headers(init_data))
    assert resp.status_code == 200

    # Rewind ``last_login_at`` by 10 minutes — past the 0-second
    # debounce (so the next request bumps ``login_count``) but
    # well inside the 30-min session gap.
    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 902002)
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        user.last_login_at = utcnow() - timedelta(minutes=10)
        await session.commit()

    resp = await client.get("/api/me", headers=auth_headers(init_data))
    assert resp.status_code == 200

    async with async_session() as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        # Second ping landed (login_count bumped), but inside the
        # session gap so sessions_count stays at the first-touch
        # value of 1.
        assert user.login_count == 2
        assert user.sessions_count == 1


async def test_sessions_count_bumps_after_session_gap(client, monkeypatch) -> None:
    """Crossing the session gap bumps ``sessions_count`` — the
    "came back after lunch" event the audit asked for."""
    from backend.app import deps
    from backend.app.db import async_session
    from backend.app.models import User

    monkeypatch.setattr(deps, "_LAST_LOGIN_DEBOUNCE", timedelta(seconds=0))
    # Shrink the session gap so the rewind below is small enough
    # to not race the test clock; the production default stays at
    # 30 min, this only affects this test process.
    monkeypatch.setattr(deps, "_SESSION_GAP", timedelta(minutes=1))

    init_data = signed_init_data(902003, "a3_cross_gap")
    resp = await client.get("/api/me", headers=auth_headers(init_data))
    assert resp.status_code == 200

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 902003)
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        # Rewind well past the (shortened) 1-min session gap.
        user.last_login_at = utcnow() - timedelta(minutes=10)
        await session.commit()

    resp = await client.get("/api/me", headers=auth_headers(init_data))
    assert resp.status_code == 200

    async with async_session() as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        assert user.login_count == 2
        assert user.sessions_count == 2
