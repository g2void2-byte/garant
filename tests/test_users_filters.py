"""PR-4 — Continental search filter sheet wiring.

``GET /api/users`` gained query params for the bottom-sheet filters from
Continental: rating bucket, deals bucket, deposit_min, prefix tier, and
registration date range. Each test pins one filter at a time so a
regression on an unrelated branch is immediately obvious.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import User
from backend.app.time_utils import utcnow


async def _make_user(
    tg: int,
    username: str,
    *,
    good: int = 0,
    bad: int = 0,
    deals_total: int = 0,
    deposit_total: float = 0.0,
    is_admin: bool = False,
    is_arbiter: bool = False,
    created_at: datetime | None = None,
) -> int:
    async with async_session() as session:
        u = User(
            tg_user_id=tg,
            username=username,
            display_name=username.capitalize(),
            good=good,
            bad=bad,
            deals_total=deals_total,
            deposit_total=deposit_total,
            is_admin=is_admin,
            is_arbiter=is_arbiter,
        )
        session.add(u)
        await session.commit()
        if created_at is not None:
            # ``created_at`` has a server_default, so we set it after insert.
            u.created_at = created_at
            await session.commit()
        await session.refresh(u)
        return u.id


async def _usernames(client, **params: object) -> list[str]:
    resp = await client.get("/api/users", params=params)
    assert resp.status_code == 200, resp.text
    return [u["username"] for u in resp.json()]


@pytest.mark.asyncio
async def test_users_default_listing_unchanged(client):
    """The default call returns rows ordered by deals_total desc — same as before PR-4."""
    await _make_user(100, "low", deals_total=1)
    await _make_user(101, "mid", deals_total=10)
    await _make_user(102, "top", deals_total=100)
    names = await _usernames(client)
    assert names == ["top", "mid", "low"]


@pytest.mark.asyncio
async def test_rating_bucket_5_0(client):
    """Bucket ``5.0`` only matches users with a perfect rating."""
    await _make_user(200, "perfect", good=20, bad=0)
    await _make_user(201, "fourpointfive", good=9, bad=1)  # rating 4.5
    names = await _usernames(client, rating="5.0")
    assert names == ["perfect"]


@pytest.mark.asyncio
async def test_rating_bucket_lt_3_5(client):
    """Bucket ``lt3.5`` matches users with rating < 3.5 (including zero-review)."""
    await _make_user(300, "weak", good=2, bad=8)  # rating 1.0
    await _make_user(301, "strong", good=10, bad=0)  # rating 5.0
    await _make_user(302, "noreviews")  # rating 0.0
    names = await _usernames(client, rating="lt3.5")
    assert set(names) == {"weak", "noreviews"}
    assert "strong" not in names


@pytest.mark.asyncio
async def test_rating_bucket_invalid(client):
    resp = await client.get("/api/users", params={"rating": "bogus"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_deals_bucket_0_10(client):
    await _make_user(400, "rookie", deals_total=5)
    await _make_user(401, "midlevel", deals_total=25)
    await _make_user(402, "veteran", deals_total=500)
    names = await _usernames(client, deals="0-10")
    assert names == ["rookie"]


@pytest.mark.asyncio
async def test_deals_bucket_101_plus(client):
    await _make_user(500, "rookie", deals_total=5)
    await _make_user(501, "veteran", deals_total=200)
    names = await _usernames(client, deals="101+")
    assert names == ["veteran"]


@pytest.mark.asyncio
async def test_deposit_min(client):
    await _make_user(600, "broke", deposit_total=0)
    await _make_user(601, "rich", deposit_total=1000.50)
    names = await _usernames(client, deposit_min=500)
    assert names == ["rich"]


@pytest.mark.asyncio
async def test_status_admin(client):
    await _make_user(700, "alice")
    await _make_user(701, "admin1", is_admin=True)
    await _make_user(703, "arb1", is_arbiter=True)
    assert await _usernames(client, status="5") == ["admin1"]


@pytest.mark.asyncio
async def test_status_moderator_retired(client):
    """Tier 4 (moderator) was dropped; the API rejects it as unknown."""
    resp = await client.get("/api/users", params={"status": "4"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_status_arbiter(client):
    await _make_user(900, "alice")
    await _make_user(901, "admin1", is_admin=True)
    await _make_user(903, "arb1", is_arbiter=True)
    assert await _usernames(client, status="3") == ["arb1"]


@pytest.mark.asyncio
async def test_status_invalid(client):
    resp = await client.get("/api/users", params={"status": "9"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_registration_date_range(client):
    now = utcnow()
    await _make_user(1000, "old", created_at=now - timedelta(days=365))
    await _make_user(1001, "recent", created_at=now - timedelta(days=2))

    today = now.date().isoformat()
    last_week = (now - timedelta(days=7)).date().isoformat()
    names = await _usernames(client, reg_from=last_week, reg_to=today)
    assert names == ["recent"]


@pytest.mark.asyncio
async def test_filters_compose(client):
    """Multiple filters AND together."""
    await _make_user(1100, "match", good=10, bad=0, deals_total=50, is_arbiter=True)
    await _make_user(1101, "wrongrating", good=1, bad=9, deals_total=50, is_arbiter=True)
    await _make_user(1102, "wrongdeals", good=10, bad=0, deals_total=1, is_arbiter=True)
    await _make_user(1103, "notarbiter", good=10, bad=0, deals_total=50)

    names = await _usernames(client, rating="5.0", deals="11-50", status="3")
    assert names == ["match"]


@pytest.mark.asyncio
async def test_user_out_no_moderator_field(client):
    """After the moderator role retirement, no row reports the flag."""
    await _make_user(1200, "alice", is_admin=True)
    resp = await client.get("/api/users")
    assert resp.status_code == 200
    by_name = {u["username"]: u for u in resp.json()}
    assert "is_moderator" not in by_name["alice"]
    assert by_name["alice"]["prefix"] == "admin"
    assert by_name["alice"]["admin"] == 5


@pytest.mark.asyncio
async def test_admin_level_is_5(client):
    """Continental encodes admin tier as int 5."""
    await _make_user(1300, "adminx", is_admin=True)
    resp = await client.get("/api/users")
    by_name = {u["username"]: u for u in resp.json()}
    assert by_name["adminx"]["admin"] == 5


# Silence ruff: ``select`` reserved for ad-hoc DB peeking in this test file.
_ = select
