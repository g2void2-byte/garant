"""PR-3 — service detail + comments endpoints.

Covers ``GET /api/services/{id}`` (detail + rating aggregate), and the
new ``/comments`` sub-resource (list, create, delete with author/owner/
admin permissions).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import Category, Service, ServiceComment, ServiceStatus, User
from backend.app.time_utils import utcnow
from tests.helpers import auth_headers, signed_init_data


async def _seed_category(slug: str = "design") -> int:
    async with async_session() as session:
        existing = (
            await session.execute(select(Category).where(Category.slug == slug))
        ).scalar_one_or_none()
        if existing:
            return existing.id
        cat = Category(slug=slug, name=slug, icon="")
        session.add(cat)
        await session.commit()
        await session.refresh(cat)
        return cat.id


async def _seed_user(tg: int, username: str) -> int:
    async with async_session() as session:
        u = User(tg_user_id=tg, username=username, display_name=username.capitalize())
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u.id


async def _seed_service(
    owner_id: int,
    category_id: int,
    *,
    title: str = "Test service",
    status: ServiceStatus = ServiceStatus.active,
) -> int:
    async with async_session() as session:
        s = Service(
            owner_id=owner_id,
            category_id=category_id,
            title=title,
            description="",
            price=10,
            status=status,
        )
        session.add(s)
        await session.commit()
        await session.refresh(s)
        return s.id


@pytest.mark.asyncio
async def test_get_service_detail_returns_owner_card_and_zero_stats(client):
    cat_id = await _seed_category()
    owner_id = await _seed_user(1001, "owner")
    viewer_init = signed_init_data(1002, "viewer")
    svc_id = await _seed_service(owner_id, cat_id, title="Brand identity")

    resp = await client.get(f"/api/services/{svc_id}", headers=auth_headers(viewer_init))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == svc_id
    assert body["title"] == "Brand identity"
    assert body["owner"]["username"] == "owner"
    assert body["owner"]["rating"] == 0.0
    assert body["owner"]["deals_count"] == 0
    assert body["comments_count"] == 0
    assert body["rating_avg"] is None
    assert body["rating_count"] == 0


@pytest.mark.asyncio
async def test_get_service_detail_404_for_unknown(client):
    init = signed_init_data(1003, "viewer")
    resp = await client.get("/api/services/9999", headers=auth_headers(init))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_service_detail_hides_paused_from_strangers(client):
    cat_id = await _seed_category()
    owner_id = await _seed_user(1004, "ownerp")
    svc_id = await _seed_service(owner_id, cat_id, status=ServiceStatus.paused)

    stranger_init = signed_init_data(1005, "stranger")
    resp = await client.get(f"/api/services/{svc_id}", headers=auth_headers(stranger_init))
    assert resp.status_code == 404

    # Owner can still see their paused service.
    owner_init = signed_init_data(1004, "ownerp")
    resp = await client.get(f"/api/services/{svc_id}", headers=auth_headers(owner_init))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_create_comment_appears_in_list_and_updates_aggregates(client):
    cat_id = await _seed_category()
    owner_id = await _seed_user(1006, "owner2")
    viewer_init = signed_init_data(1007, "viewer2")
    svc_id = await _seed_service(owner_id, cat_id)

    resp = await client.post(
        f"/api/services/{svc_id}/comments",
        json={"text": "Recommend!", "rating": 5},
        headers=auth_headers(viewer_init),
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["text"] == "Recommend!"
    assert created["rating"] == 5
    assert created["author_username"] == "viewer2"

    list_resp = await client.get(
        f"/api/services/{svc_id}/comments", headers=auth_headers(viewer_init)
    )
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    assert items[0]["id"] == created["id"]

    detail = await client.get(f"/api/services/{svc_id}", headers=auth_headers(viewer_init))
    assert detail.json()["comments_count"] == 1
    assert detail.json()["rating_avg"] == 5.0
    assert detail.json()["rating_count"] == 1


@pytest.mark.asyncio
async def test_list_comments_supports_limit_offset(client):
    cat_id = await _seed_category()
    owner_id = await _seed_user(1020, "owner_page")
    author_id = await _seed_user(1021, "comment_page")
    viewer_init = signed_init_data(1022, "comment_viewer")
    svc_id = await _seed_service(owner_id, cat_id)

    async with async_session() as session:
        now = utcnow()
        comments = [
            ServiceComment(
                service_id=svc_id,
                author_id=author_id,
                text=f"paged comment {idx}",
                rating=5,
                created_at=now - timedelta(minutes=idx),
            )
            for idx in range(4)
        ]
        session.add_all(comments)
        await session.commit()
        expected_ids = [comments[1].id, comments[2].id]

    resp = await client.get(
        f"/api/services/{svc_id}/comments",
        params={"limit": 2, "offset": 1},
        headers=auth_headers(viewer_init),
    )
    assert resp.status_code == 200, resp.text
    assert int(resp.headers["X-Total-Count"]) == 4
    assert [row["id"] for row in resp.json()] == expected_ids


@pytest.mark.asyncio
async def test_owner_cannot_comment_on_own_service(client):
    cat_id = await _seed_category()
    owner_id = await _seed_user(1008, "self_owner")
    svc_id = await _seed_service(owner_id, cat_id)

    owner_init = signed_init_data(1008, "self_owner")
    resp = await client.post(
        f"/api/services/{svc_id}/comments",
        json={"text": "great", "rating": 5},
        headers=auth_headers(owner_init),
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_empty_comment_without_rating_rejected(client):
    cat_id = await _seed_category()
    owner_id = await _seed_user(1009, "owner3")
    viewer_init = signed_init_data(1010, "viewer3")
    svc_id = await _seed_service(owner_id, cat_id)

    resp = await client.post(
        f"/api/services/{svc_id}/comments",
        json={"text": "", "rating": None},
        headers=auth_headers(viewer_init),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_rating_out_of_range_rejected(client):
    cat_id = await _seed_category()
    owner_id = await _seed_user(1011, "owner4")
    viewer_init = signed_init_data(1012, "viewer4")
    svc_id = await _seed_service(owner_id, cat_id)

    resp = await client.post(
        f"/api/services/{svc_id}/comments",
        json={"text": "x", "rating": 6},
        headers=auth_headers(viewer_init),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_author_can_delete_own_comment(client):
    cat_id = await _seed_category()
    owner_id = await _seed_user(1013, "owner5")
    viewer_init = signed_init_data(1014, "viewer5")
    svc_id = await _seed_service(owner_id, cat_id)

    create_resp = await client.post(
        f"/api/services/{svc_id}/comments",
        json={"text": "good", "rating": 4},
        headers=auth_headers(viewer_init),
    )
    cid = create_resp.json()["id"]
    del_resp = await client.delete(
        f"/api/services/{svc_id}/comments/{cid}", headers=auth_headers(viewer_init)
    )
    assert del_resp.status_code == 200
    async with async_session() as session:
        remaining = (
            await session.execute(select(ServiceComment).where(ServiceComment.id == cid))
        ).scalar_one_or_none()
        assert remaining is None


@pytest.mark.asyncio
async def test_owner_can_delete_others_comment(client):
    cat_id = await _seed_category()
    owner_id = await _seed_user(1015, "owner6")
    viewer_init = signed_init_data(1016, "viewer6")
    svc_id = await _seed_service(owner_id, cat_id)

    create_resp = await client.post(
        f"/api/services/{svc_id}/comments",
        json={"text": "good", "rating": 4},
        headers=auth_headers(viewer_init),
    )
    cid = create_resp.json()["id"]

    owner_init = signed_init_data(1015, "owner6")
    del_resp = await client.delete(
        f"/api/services/{svc_id}/comments/{cid}", headers=auth_headers(owner_init)
    )
    assert del_resp.status_code == 200


@pytest.mark.asyncio
async def test_third_party_cannot_delete_others_comment(client):
    cat_id = await _seed_category()
    owner_id = await _seed_user(1017, "owner7")
    viewer_init = signed_init_data(1018, "viewer7")
    other_init = signed_init_data(1019, "other7")
    svc_id = await _seed_service(owner_id, cat_id)

    create_resp = await client.post(
        f"/api/services/{svc_id}/comments",
        json={"text": "good", "rating": 4},
        headers=auth_headers(viewer_init),
    )
    cid = create_resp.json()["id"]
    del_resp = await client.delete(
        f"/api/services/{svc_id}/comments/{cid}", headers=auth_headers(other_init)
    )
    assert del_resp.status_code == 403
