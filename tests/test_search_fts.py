"""P3.4 — full-text search coverage.

Verifies the catalog (`/api/services`) and user-search (`/api/users`)
endpoints query the new GIN-indexed ``search_vector`` columns instead
of falling back to ILIKE. Each test seeds rows, hits the public API,
and asserts on ordering / membership.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import Category, Service, ServiceStatus, User
from backend.app.search import build_prefix_tsquery
from tests.helpers import auth_headers, signed_init_data

# ── tsquery builder ────────────────────────────────────────────────────────


def test_tsquery_builder_handles_single_token():
    assert build_prefix_tsquery("foo") == "foo:*"


def test_tsquery_builder_handles_multiple_tokens():
    assert build_prefix_tsquery("foo bar") == "foo:* & bar:*"


def test_tsquery_builder_strips_punctuation_and_keeps_cyrillic():
    assert build_prefix_tsquery("привет!  test??") == "привет:* & test:*"


def test_tsquery_builder_returns_none_for_empty_or_punct_only():
    assert build_prefix_tsquery("") is None
    assert build_prefix_tsquery("   ") is None
    assert build_prefix_tsquery("?!.,") is None


# ── /api/services?q= ───────────────────────────────────────────────────────


async def _seed_category(slug: str = "design") -> int:
    """Replace the auto-seeded categories with a single one for predictable joins."""
    async with async_session() as session:
        result = await session.execute(select(Category).where(Category.slug == slug))
        cat = result.scalar_one_or_none()
        if cat:
            return cat.id
        cat = Category(slug=slug, name=slug, icon="")
        session.add(cat)
        await session.commit()
        await session.refresh(cat)
        return cat.id


async def _seed_user_and_service(
    tg: int,
    username: str,
    *,
    title: str,
    description: str = "",
    category_id: int,
    status: ServiceStatus = ServiceStatus.active,
) -> int:
    async with async_session() as session:
        u = User(tg_user_id=tg, username=username, display_name=username.capitalize())
        session.add(u)
        await session.flush()
        s = Service(
            owner_id=u.id,
            category_id=category_id,
            title=title,
            description=description,
            price=10,
            status=status,
        )
        session.add(s)
        await session.commit()
        await session.refresh(s)
        return s.id


@pytest.mark.asyncio
async def test_services_search_matches_title_word(client):
    cat = await _seed_category()
    s_match = await _seed_user_and_service(
        2001, "alice", title="Свежий лендинг", description="", category_id=cat
    )
    await _seed_user_and_service(
        2002, "bob", title="Ремонт кофемашины", description="", category_id=cat
    )

    init = signed_init_data(2999, "buyer")
    resp = await client.get("/api/services", params={"q": "лендинг"}, headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    ids = [row["id"] for row in resp.json()]
    assert ids == [s_match]


@pytest.mark.asyncio
async def test_services_search_does_prefix_match(client):
    cat = await _seed_category()
    s_match = await _seed_user_and_service(
        2011, "alice", title="Создание лендинга", description="", category_id=cat
    )
    await _seed_user_and_service(
        2012, "bob", title="Ремонт кофемашины", description="", category_id=cat
    )

    init = signed_init_data(2999, "buyer")
    # Query "ленди" must still find "лендинга" — that's the ILIKE-feel we kept.
    resp = await client.get("/api/services", params={"q": "ленди"}, headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    ids = [row["id"] for row in resp.json()]
    assert ids == [s_match]


@pytest.mark.asyncio
async def test_services_search_falls_into_description_field(client):
    cat = await _seed_category()
    s_match = await _seed_user_and_service(
        2021,
        "alice",
        title="Услуга",
        description="Делаю редизайн интерфейсов мобильных приложений",
        category_id=cat,
    )
    await _seed_user_and_service(
        2022,
        "bob",
        title="Услуга",
        description="Пишу тексты для блога",
        category_id=cat,
    )

    init = signed_init_data(2999, "buyer")
    resp = await client.get("/api/services", params={"q": "редизайн"}, headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    ids = [row["id"] for row in resp.json()]
    assert ids == [s_match]


@pytest.mark.asyncio
async def test_services_search_ranks_title_above_description(client):
    """Title hit (weight A) must rank above description-only hit (weight B)."""
    cat = await _seed_category()
    s_description_only = await _seed_user_and_service(
        2031,
        "alice",
        title="Что-то общее",
        description="Опытный python разработчик",
        category_id=cat,
    )
    s_title_hit = await _seed_user_and_service(
        2032,
        "bob",
        title="Python разработчик",
        description="любой стек",
        category_id=cat,
    )

    init = signed_init_data(2999, "buyer")
    resp = await client.get("/api/services", params={"q": "python"}, headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    ids = [row["id"] for row in resp.json()]
    assert ids == [s_title_hit, s_description_only]


@pytest.mark.asyncio
async def test_services_search_empty_query_returns_all(client):
    cat = await _seed_category()
    await _seed_user_and_service(2041, "alice", title="A service", category_id=cat)
    await _seed_user_and_service(2042, "bob", title="B service", category_id=cat)

    init = signed_init_data(2999, "buyer")
    resp = await client.get("/api/services", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_services_search_punctuation_only_returns_all(client):
    """User typed only punctuation → ts_q is None → no FTS filter applied."""
    cat = await _seed_category()
    await _seed_user_and_service(2051, "alice", title="A service", category_id=cat)
    await _seed_user_and_service(2052, "bob", title="B service", category_id=cat)

    init = signed_init_data(2999, "buyer")
    resp = await client.get("/api/services", params={"q": "??!"}, headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 2


# ── /api/users?q= ──────────────────────────────────────────────────────────


async def _seed_user_only(tg: int, username: str, display_name: str = "") -> int:
    async with async_session() as session:
        u = User(
            tg_user_id=tg,
            username=username,
            display_name=display_name or username.capitalize(),
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u.id


@pytest.mark.asyncio
async def test_users_search_matches_username(client):
    await _seed_user_only(3001, "alice_landing")
    await _seed_user_only(3002, "bob_repair")

    init = signed_init_data(3999, "searcher")
    resp = await client.get("/api/users", params={"q": "landing"}, headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    usernames = [row["username"] for row in resp.json()]
    assert usernames == ["alice_landing"]


@pytest.mark.asyncio
async def test_users_search_matches_display_name(client):
    await _seed_user_only(3011, "u1", display_name="Иван Петров")
    await _seed_user_only(3012, "u2", display_name="Сергей Иванов")

    init = signed_init_data(3999, "searcher")
    # Both should match — Иван is a substring of Иванов via :* prefix and
    # equals the first token of "Иван Петров".
    resp = await client.get("/api/users", params={"q": "Иван"}, headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    usernames = sorted(row["username"] for row in resp.json())
    assert usernames == ["u1", "u2"]


@pytest.mark.asyncio
async def test_users_search_ranks_username_above_display_name(client):
    """Username hit (weight A) must rank above display_name-only hit (weight B)."""
    u_display_only = await _seed_user_only(3021, "x_user", display_name="Designer")
    u_username_hit = await _seed_user_only(3022, "designer", display_name="Random")

    init = signed_init_data(3999, "searcher")
    resp = await client.get("/api/users", params={"q": "designer"}, headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    ids = [row["id"] for row in resp.json()]
    assert ids == [u_username_hit, u_display_only]


@pytest.mark.asyncio
async def test_users_search_empty_keeps_deals_total_ordering(client):
    """Without q, the legacy ordering (deals_total desc) must still apply."""
    async with async_session() as session:
        a = User(tg_user_id=3101, username="quiet", display_name="Quiet", deals_total=2)
        b = User(tg_user_id=3102, username="busy", display_name="Busy", deals_total=99)
        session.add_all([a, b])
        await session.commit()

    init = signed_init_data(3999, "searcher")
    resp = await client.get("/api/users", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    usernames = [row["username"] for row in resp.json()]
    # Busy first (deals_total=99), then quiet (deals_total=2).
    assert usernames[:2] == ["busy", "quiet"]
