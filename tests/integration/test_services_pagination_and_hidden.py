"""R6 / R7 — services list pagination + hidden-owner filtering.

* **R6 / H-10** — ``GET /api/services`` accepts ``limit`` and
  ``offset`` query parameters and returns the total via the
  ``X-Total-Count`` response header. Default behaviour stays
  backward-compatible (limit 100, cap 200) so existing TanStack-Query
  clients keep working.
* **R7 / H-12** — services owned by a user with
  ``is_hidden_profile=true`` are excluded from the public catalog.
  The owner themself and admins still see those rows so they can
  manage paused/active state.
"""

from __future__ import annotations

from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import Category, Service, ServiceStatus, User
from tests.helpers import auth_headers, signed_init_data


async def _bootstrap(client, *, tg_user_id: int, username: str) -> int:
    init = signed_init_data(tg_user_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    # Bypass gating for list tests by giving the bootstrapped user deals_total >= 1
    from sqlalchemy import update

    async with async_session() as session:
        await session.execute(
            update(User).where(User.tg_user_id == tg_user_id).values(deals_total=1)
        )
        await session.commit()
    return resp.json()["id"]


async def _seed_active_services(owner_id: int, count: int, prefix: str = "svc") -> list[int]:
    """Insert ``count`` active services owned by ``owner_id``."""
    async with async_session() as session:
        cat = (await session.execute(select(Category).limit(1))).scalar_one()
        ids: list[int] = []
        for i in range(count):
            s = Service(
                owner_id=owner_id,
                category_id=cat.id,
                title=f"{prefix}-{i:03d}",
                description="",
                price=10 + i,
                status=ServiceStatus.active,
            )
            session.add(s)
            await session.flush()
            ids.append(s.id)
        await session.commit()
        return ids


# ── R6 — pagination ─────────────────────────────────────────────────────


async def test_default_limit_is_capped_at_100(client):
    """No params → at most 100 rows even when more exist."""
    owner_id = await _bootstrap(client, tg_user_id=14001, username="lots_owner")
    await _seed_active_services(owner_id, count=120, prefix="default")

    await _bootstrap(client, tg_user_id=14002, username="caller_p1")
    caller_init = signed_init_data(14002, "caller_p1")
    resp = await client.get("/api/services", headers=auth_headers(caller_init))
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 100


async def test_explicit_limit_caps_response(client):
    owner_id = await _bootstrap(client, tg_user_id=14003, username="few_owner")
    await _seed_active_services(owner_id, count=8, prefix="explicit")

    await _bootstrap(client, tg_user_id=14004, username="caller_p2")
    caller_init = signed_init_data(14004, "caller_p2")
    resp = await client.get("/api/services?limit=3", headers=auth_headers(caller_init))
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 3


async def test_offset_skips_rows(client):
    """A query for limit=2 offset=0 vs limit=2 offset=2 returns two
    disjoint slices of the deterministic ``created_at DESC`` ordering."""
    owner_id = await _bootstrap(client, tg_user_id=14005, username="paginator_owner")
    await _seed_active_services(owner_id, count=5, prefix="paginate")

    await _bootstrap(client, tg_user_id=14006, username="caller_p3")
    caller_init = signed_init_data(14006, "caller_p3")
    page_a = (
        await client.get("/api/services?limit=2&offset=0", headers=auth_headers(caller_init))
    ).json()
    page_b = (
        await client.get("/api/services?limit=2&offset=2", headers=auth_headers(caller_init))
    ).json()

    assert len(page_a) == 2
    assert len(page_b) == 2
    a_ids = {row["id"] for row in page_a}
    b_ids = {row["id"] for row in page_b}
    assert a_ids.isdisjoint(b_ids)


async def test_x_total_count_header_reflects_unpaginated_count(client):
    """The header is the row count BEFORE limit/offset is applied so
    the UI can render ``Showing N–M of T``."""
    owner_id = await _bootstrap(client, tg_user_id=14007, username="total_owner")
    await _seed_active_services(owner_id, count=12, prefix="total")

    await _bootstrap(client, tg_user_id=14008, username="caller_p4")
    caller_init = signed_init_data(14008, "caller_p4")
    resp = await client.get("/api/services?limit=3", headers=auth_headers(caller_init))
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 3
    assert resp.headers["x-total-count"] == "12"


async def test_limit_over_200_is_rejected(client):
    """Hard cap at 200 so the catalogue can't be DoS'd by an absurd
    page size."""
    caller_init = signed_init_data(14009, "caller_p5")
    resp = await client.get("/api/services?limit=500", headers=auth_headers(caller_init))
    assert resp.status_code == 422


async def test_negative_offset_is_rejected(client):
    caller_init = signed_init_data(14010, "caller_p6")
    resp = await client.get("/api/services?offset=-1", headers=auth_headers(caller_init))
    assert resp.status_code == 422


# ── R7 — hidden-owner filter ────────────────────────────────────────────


async def _make_hidden_owner(client, tg_user_id: int, username: str) -> int:
    """Bootstrap a user, mark their profile as hidden, return their id."""
    uid = await _bootstrap(client, tg_user_id=tg_user_id, username=username)
    async with async_session() as session:
        u = await session.get(User, uid)
        u.is_hidden_profile = True
        await session.commit()
    return uid


async def test_hidden_owner_services_excluded_from_public_catalog(client):
    """A service owned by a hidden user must NOT appear in the
    no-filter (``GET /api/services``) catalog response."""
    hidden_id = await _make_hidden_owner(client, 14101, "hidden_owner")
    visible_id = await _bootstrap(client, tg_user_id=14102, username="visible_owner")
    await _seed_active_services(hidden_id, count=3, prefix="HIDDEN")
    await _seed_active_services(visible_id, count=3, prefix="VISIBLE")

    await _bootstrap(client, tg_user_id=14103, username="caller_hide_1")
    caller_init = signed_init_data(14103, "caller_hide_1")
    resp = await client.get("/api/services", headers=auth_headers(caller_init))
    assert resp.status_code == 200, resp.text
    titles = [row["title"] for row in resp.json()]
    assert all(not t.startswith("HIDDEN") for t in titles)
    assert any(t.startswith("VISIBLE") for t in titles)
    # X-Total-Count must also exclude hidden rows.
    assert resp.headers["x-total-count"] == "3"


async def test_hidden_owner_services_excluded_when_filtering_by_username(client):
    """``?owner=hidden_user`` requested by an outside caller also
    returns empty + total 0 (we don't want to leak ``is_hidden_profile``
    state via a side-channel)."""
    hidden_id = await _make_hidden_owner(client, 14111, "hidden_owner_2")
    await _seed_active_services(hidden_id, count=4, prefix="HIDDEN2")

    await _bootstrap(client, tg_user_id=14112, username="caller_hide_2")
    caller_init = signed_init_data(14112, "caller_hide_2")
    resp = await client.get("/api/services?owner=hidden_owner_2", headers=auth_headers(caller_init))
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
    assert resp.headers["x-total-count"] == "0"


async def test_hidden_owner_sees_own_services(client):
    """When the hidden owner pulls ``?owner=<themself>`` they still see
    their own catalogue (otherwise they couldn't manage it)."""
    hidden_id = await _make_hidden_owner(client, 14121, "self_owner")
    await _seed_active_services(hidden_id, count=2, prefix="MINE")

    self_init = signed_init_data(14121, "self_owner")
    resp = await client.get("/api/services?owner=self_owner", headers=auth_headers(self_init))
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 2
    assert resp.headers["x-total-count"] == "2"


async def test_admin_sees_hidden_owner_services(client):
    """Admins are allowed past the ``is_hidden_profile`` curtain so a
    moderator can investigate complaints without the owner knowing
    they've been pulled out of hiding."""
    hidden_id = await _make_hidden_owner(client, 14131, "hidden_owner_3")
    await _seed_active_services(hidden_id, count=2, prefix="HIDDEN3")

    admin_init = signed_init_data(14132, "admin_p4")
    admin_id = await _bootstrap(client, tg_user_id=14132, username="admin_p4")
    async with async_session() as session:
        u = await session.get(User, admin_id)
        u.is_admin = True
        await session.commit()

    resp = await client.get("/api/services?owner=hidden_owner_3", headers=auth_headers(admin_init))
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 2
