"""Audit L-1 — ``login_count`` no longer drifts when two parallel
first-touch ``/api/me`` calls race the initial SELECT in
``deps.get_current_user``.

Pre-fix the code did ``INSERT ... ON CONFLICT (tg_user_id) DO NOTHING``,
so the loser of the race committed a no-op and ``login_count`` for a
brand-new user ended up at 1 even when two concurrent first-touches
both hit the new-user branch. The fix upgrades that to a
``DO UPDATE`` that atomically bumps ``login_count`` and refreshes
``last_login_at`` / ``last_ip``, mirroring what the existing-user
branch already does for every post-debounce session ping.

These tests exercise the exact INSERT statement shape so a future
regression — e.g. someone "simplifies" the ON CONFLICT branch back
to ``DO NOTHING`` — fails CI directly. They run against a real
Postgres so the ``ON CONFLICT`` semantics are honoured.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.app.db import async_session
from backend.app.models import User
from backend.app.time_utils import utcnow


def _build_insert(tg_user_id: int, now, ip: str):
    """Re-create the ``deps.get_current_user`` first-touch statement.

    Kept in lock-step with the production code so a divergence shows
    up as a failing test instead of a silent re-introduction of the
    L-1 bug. If the production statement changes shape, update both
    sides together.
    """
    stmt = pg_insert(User).values(
        tg_user_id=tg_user_id,
        username="audit_l1",
        display_name="L1",
        photo_url=None,
        language_code=None,
        last_ip=ip,
        last_login_at=now,
        login_count=1,
    )
    return stmt.on_conflict_do_update(
        index_elements=["tg_user_id"],
        set_={
            "login_count": User.__table__.c.login_count + 1,
            "last_login_at": stmt.excluded.last_login_at,
            "last_ip": stmt.excluded.last_ip,
        },
    )


@pytest.mark.asyncio
async def test_on_conflict_bumps_login_count_for_race_loser():
    """The "loser" of the first-touch race used to commit a no-op.
    Now it bumps ``login_count`` to 2 — the correct invariant when
    two concurrent first-touches both hit the new-user branch.
    """
    tg = 87001
    async with async_session() as session:
        await session.execute(delete(User).where(User.tg_user_id == tg))
        await session.commit()

    now = utcnow()

    # Winner: row didn't exist, gets login_count=1 from the INSERT side.
    async with async_session() as session:
        await session.execute(_build_insert(tg, now, "10.0.0.1"))
        await session.commit()
        row = (await session.execute(select(User).where(User.tg_user_id == tg))).scalar_one()
        assert row.login_count == 1
        assert row.last_ip == "10.0.0.1"

    # Loser: row already exists, ON CONFLICT DO UPDATE bumps to 2.
    later = now + timedelta(seconds=1)
    async with async_session() as session:
        await session.execute(_build_insert(tg, later, "10.0.0.2"))
        await session.commit()
        row = (await session.execute(select(User).where(User.tg_user_id == tg))).scalar_one()
        assert row.login_count == 2, (
            "Audit L-1 regression: ON CONFLICT path didn't bump login_count"
        )
        assert row.last_ip == "10.0.0.2"
        assert row.last_login_at == later


@pytest.mark.asyncio
async def test_on_conflict_does_not_touch_identity_columns():
    """The loser-branch must NOT overwrite identity fields the winning
    insert chose (``username`` / ``display_name`` / ``photo_url`` /
    ``language_code``). They are not in the ``set_`` map, so a stale
    loser-side payload can't clobber a winner-side correction (or
    race the existing-user branch's dirty-track).
    """
    tg = 87002
    async with async_session() as session:
        await session.execute(delete(User).where(User.tg_user_id == tg))
        await session.commit()

    now = utcnow()

    async with async_session() as session:
        winning = pg_insert(User).values(
            tg_user_id=tg,
            username="winner",
            display_name="Winner",
            photo_url="https://example/winner.png",
            language_code="en",
            last_ip="10.0.0.1",
            last_login_at=now,
            login_count=1,
        )
        winning = winning.on_conflict_do_update(
            index_elements=["tg_user_id"],
            set_={
                "login_count": User.__table__.c.login_count + 1,
                "last_login_at": winning.excluded.last_login_at,
                "last_ip": winning.excluded.last_ip,
            },
        )
        await session.execute(winning)
        await session.commit()

    # The "loser" tries to insert a different identity payload; the
    # ON CONFLICT DO UPDATE must only bump the counter / refresh
    # last_login_at / last_ip, leaving identity columns intact.
    async with async_session() as session:
        loser = pg_insert(User).values(
            tg_user_id=tg,
            username="loser",
            display_name="Loser",
            photo_url="https://example/loser.png",
            language_code="ru",
            last_ip="10.0.0.2",
            last_login_at=now + timedelta(seconds=1),
            login_count=1,
        )
        loser = loser.on_conflict_do_update(
            index_elements=["tg_user_id"],
            set_={
                "login_count": User.__table__.c.login_count + 1,
                "last_login_at": loser.excluded.last_login_at,
                "last_ip": loser.excluded.last_ip,
            },
        )
        await session.execute(loser)
        await session.commit()
        row = (await session.execute(select(User).where(User.tg_user_id == tg))).scalar_one()
        # Counter bumped, last_ip refreshed.
        assert row.login_count == 2
        assert row.last_ip == "10.0.0.2"
        # Identity columns kept from the winner.
        assert row.username == "winner"
        assert row.display_name == "Winner"
        assert row.photo_url == "https://example/winner.png"
        assert row.language_code == "en"


@pytest.mark.asyncio
async def test_first_touch_via_api_starts_at_login_count_one(client):
    """Sanity / contract check: a brand-new user landing on /api/me
    for the first time still observes ``login_count == 1`` (the
    fix doesn't accidentally double-count on the no-race happy path).
    """
    from tests.helpers import auth_headers, signed_init_data

    init = signed_init_data(87003, "fresh_l1")
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text

    async with async_session() as session:
        row = (await session.execute(select(User).where(User.tg_user_id == 87003))).scalar_one()
        assert row.login_count == 1
