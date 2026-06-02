from __future__ import annotations

import pytest
from sqlalchemy import select, update

from backend.app.db import async_session
from backend.app.models import Category, Service, ServiceStatus, User
from tests.helpers import auth_headers, signed_init_data

_GATED_TG = 10001
_GATED_USERNAME = "gated_user_zero_deals"

_UNGATED_TG = 10002
_UNGATED_USERNAME = "ungated_user_one_deal"

_ADMIN_TG = 10003
_ADMIN_USERNAME = "admin_user_zero_deals"


async def _setup_user(
    client, tg: int, username: str, *, deals_total: int = 0, is_admin: bool = False
) -> dict[str, str]:
    init = signed_init_data(tg, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200

    async with async_session() as session:
        await session.execute(
            update(User)
            .where(User.tg_user_id == tg)
            .values(deals_total=deals_total, is_admin=is_admin)
        )
        await session.commit()
    return auth_headers(init)


@pytest.mark.asyncio
async def test_search_gating_behavior(client, monkeypatch):
    monkeypatch.setenv("ENFORCE_SEARCH_GATING", "1")
    # 1. Setup users
    gated_headers = await _setup_user(
        client, _GATED_TG, _GATED_USERNAME, deals_total=0, is_admin=False
    )
    ungated_headers = await _setup_user(
        client, _UNGATED_TG, _UNGATED_USERNAME, deals_total=1, is_admin=False
    )
    admin_headers = await _setup_user(
        client, _ADMIN_TG, _ADMIN_USERNAME, deals_total=0, is_admin=True
    )

    # 2. Test GET /api/users
    resp = await client.get("/api/users", headers=gated_headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Минимум 1 сделка для поиска"

    resp = await client.get("/api/users", headers=ungated_headers)
    assert resp.status_code == 200

    # 3. Test GET /api/services
    resp = await client.get("/api/services", headers=gated_headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Минимум 1 сделка для поиска"

    resp = await client.get("/api/services", headers=ungated_headers)
    assert resp.status_code == 200

    resp = await client.get("/api/services", headers=admin_headers)
    assert resp.status_code == 200

    # 4. Test GET /api/categories
    resp = await client.get("/api/categories", headers=gated_headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Минимум 1 сделка для поиска"

    resp = await client.get("/api/categories", headers=ungated_headers)
    assert resp.status_code == 200

    resp = await client.get("/api/categories", headers=admin_headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_zero_deal_user_can_list_own_services(client):
    username = "zero_deal_service_owner"
    headers = await _setup_user(
        client,
        10004,
        username,
        deals_total=0,
        is_admin=False,
    )

    async with async_session() as session:
        user = (
            await session.execute(select(User).where(User.username == username))
        ).scalar_one()
        category = (await session.execute(select(Category).limit(1))).scalar_one()
        session.add(
            Service(
                owner_id=user.id,
                category_id=category.id,
                title="first-service",
                description="",
                price=10,
                status=ServiceStatus.active,
            )
        )
        await session.commit()

    browse = await client.get("/api/services", headers=headers)
    assert browse.status_code == 403
    assert browse.json()["detail"] == "Минимум 1 сделка для поиска"

    own = await client.get(f"/api/services?owner={username}", headers=headers)
    assert own.status_code == 200, own.text
    assert [row["title"] for row in own.json()] == ["first-service"]
    assert own.headers["x-total-count"] == "1"
