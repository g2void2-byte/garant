"""PR-4 — Continental search filter sheet wiring.

``GET /api/users`` gained query params for the bottom-sheet filters from
Continental: rating bucket, deals bucket, prefix tier, and registration
date range. Each test pins one filter at a time so a regression on an
unrelated branch is immediately obvious.

The ``deposit_min`` filter was retired together with
``User.deposit_total`` — the lifetime aggregate it filtered against no
longer exists.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.app.db import async_session
from backend.app.models import User
from backend.app.time_utils import utcnow
from tests.helpers import auth_headers, signed_init_data

# Audit M-1 — ``GET /api/users`` is now gated behind ``CurrentUser``
# (initData verification) and ``RLUsersList`` rate-limiting. Tests
# in this module ride a single bootstrapped caller and supply
# ``Authorization: tma ...`` on every list call. The caller is
# bootstrapped once per test via ``_caller_headers`` so each test's
# rate-limit bucket starts fresh.
_CALLER_TG = 9999
_CALLER_USERNAME = "users_filter_caller"


async def _caller_headers(client) -> dict[str, str]:
    init = signed_init_data(_CALLER_TG, _CALLER_USERNAME)
    # Bootstrap so the user row exists; ``CurrentUser`` then resolves.
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    # Bypass gating for list tests by giving the caller deals_total >= 1
    from sqlalchemy import update

    async with async_session() as session:
        await session.execute(
            update(User).where(User.username == _CALLER_USERNAME).values(deals_total=1)
        )
        await session.commit()
    return auth_headers(init)


async def _make_user(
    tg: int,
    username: str,
    *,
    good: int = 0,
    bad: int = 0,
    deals_total: int = 0,
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
    headers = await _caller_headers(client)
    resp = await client.get("/api/users", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    # The bootstrapped caller appears in the listing alongside the
    # rows each test seeds; filter it out so the per-test expectations
    # stay focused on the seeded rows. Pre-M-1 these tests were
    # anonymous and there was no caller row to filter.
    return [u["username"] for u in resp.json() if u["username"] != _CALLER_USERNAME]


@pytest.mark.asyncio
async def test_users_default_listing_unchanged(client):
    """The default call returns rows ordered by deals_total desc — same as before PR-4."""
    await _make_user(100, "low", deals_total=1)
    await _make_user(101, "mid", deals_total=10)
    await _make_user(102, "top", deals_total=100)
    names = await _usernames(client)
    assert names == ["top", "mid", "low"]


@pytest.mark.asyncio
async def test_users_listing_supports_limit_offset(client):
    await _make_user(110, "rank0", deals_total=100)
    await _make_user(111, "rank1", deals_total=90)
    await _make_user(112, "rank2", deals_total=80)
    await _make_user(113, "rank3", deals_total=70)
    headers = await _caller_headers(client)

    resp = await client.get(
        "/api/users",
        params={"limit": 2, "offset": 1},
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    assert int(resp.headers["X-Total-Count"]) >= 4
    assert [u["username"] for u in resp.json()] == ["rank1", "rank2"]


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
    headers = await _caller_headers(client)
    resp = await client.get("/api/users", params={"rating": "bogus"}, headers=headers)
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
async def test_status_admin(client):
    await _make_user(700, "alice")
    await _make_user(701, "admin1", is_admin=True)
    await _make_user(703, "arb1", is_arbiter=True)
    assert await _usernames(client, status="5") == ["admin1"]


@pytest.mark.asyncio
async def test_status_moderator_retired(client):
    """Tier 4 (moderator) was dropped; the API rejects it as unknown."""
    headers = await _caller_headers(client)
    resp = await client.get("/api/users", params={"status": "4"}, headers=headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_status_arbiter(client):
    await _make_user(900, "alice")
    await _make_user(901, "admin1", is_admin=True)
    await _make_user(903, "arb1", is_arbiter=True)
    assert await _usernames(client, status="3") == ["arb1"]


@pytest.mark.asyncio
async def test_status_invalid(client):
    headers = await _caller_headers(client)
    resp = await client.get("/api/users", params={"status": "9"}, headers=headers)
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
    headers = await _caller_headers(client)
    resp = await client.get("/api/users", headers=headers)
    assert resp.status_code == 200
    by_name = {u["username"]: u for u in resp.json()}
    assert "is_moderator" not in by_name["alice"]
    assert by_name["alice"]["prefix"] == "admin"
    assert by_name["alice"]["admin"] == 5


@pytest.mark.asyncio
async def test_admin_level_is_5(client):
    """Continental encodes admin tier as int 5."""
    await _make_user(1300, "adminx", is_admin=True)
    headers = await _caller_headers(client)
    resp = await client.get("/api/users", headers=headers)
    by_name = {u["username"]: u for u in resp.json()}
    assert by_name["adminx"]["admin"] == 5
