"""Admin content editing — services / reviews / comments."""

from __future__ import annotations

from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import (
    AdminAuditLog,
    Category,
    Review,
    Service,
    ServiceComment,
    User,
)
from tests.helpers import auth_headers, signed_init_data


async def _make_admin(client, tg_id: int = 9001, username: str = "admin") -> str:
    init = signed_init_data(tg_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    uid = resp.json()["id"]
    async with async_session() as session:
        user = await session.get(User, uid)
        assert user is not None
        user.is_admin = True
        await session.commit()
    return init


async def _bootstrap_user(client, tg_id: int, username: str) -> int:
    init = signed_init_data(tg_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _create_service(owner_id: int, *, title: str = "S") -> int:
    async with async_session() as session:
        cat = (await session.execute(select(Category))).scalars().first()
        assert cat is not None
        service = Service(
            owner_id=owner_id,
            category_id=cat.id,
            title=title,
            description="desc",
            price=10,
        )
        session.add(service)
        await session.commit()
        await session.refresh(service)
        return service.id


# ── Services ───────────────────────────────────────────────────────────────


async def test_list_user_services_forbidden_for_non_admin(client):
    owner_id = await _bootstrap_user(client, 100, "owner")
    init = signed_init_data(101, "other")
    await client.get("/api/me", headers=auth_headers(init))
    resp = await client.get(f"/api/admin/users/{owner_id}/services", headers=auth_headers(init))
    assert resp.status_code == 403


async def test_list_user_services_returns_owned(client):
    owner_id = await _bootstrap_user(client, 100, "owner")
    s1 = await _create_service(owner_id, title="A")
    s2 = await _create_service(owner_id, title="B")
    admin_init = await _make_admin(client)
    resp = await client.get(
        f"/api/admin/users/{owner_id}/services", headers=auth_headers(admin_init)
    )
    assert resp.status_code == 200
    ids = {s["id"] for s in resp.json()}
    assert s1 in ids and s2 in ids


async def test_update_service_changes_fields_and_writes_audit(client):
    owner_id = await _bootstrap_user(client, 100, "owner")
    sid = await _create_service(owner_id)
    admin_init = await _make_admin(client)
    resp = await client.post(
        f"/api/admin/services/{sid}",
        json={
            "title": "Updated",
            "price": 99.5,
            "deposit": 5,
            "deals_count": 7,
            "rating_manual": 4.5,
            "status": "paused",
        },
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "Updated"
    assert body["price"] == 99.5
    assert body["deposit"] == 5.0
    assert body["deals_count"] == 7
    assert body["rating_manual"] == 4.5
    assert body["status"] == "paused"
    async with async_session() as session:
        rows = list(
            (
                await session.execute(
                    select(AdminAuditLog).where(AdminAuditLog.action == "service.edit")
                )
            ).scalars()
        )
    assert len(rows) == 1


async def test_update_service_validates_rating_range(client):
    owner_id = await _bootstrap_user(client, 100, "owner")
    sid = await _create_service(owner_id)
    admin_init = await _make_admin(client)
    resp = await client.post(
        f"/api/admin/services/{sid}",
        json={"rating_manual": 10},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 422


async def test_update_service_no_change_no_audit_row(client):
    owner_id = await _bootstrap_user(client, 100, "owner")
    sid = await _create_service(owner_id, title="Same")
    admin_init = await _make_admin(client)
    # send same value
    resp = await client.post(
        f"/api/admin/services/{sid}",
        json={"title": "Same"},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 200
    async with async_session() as session:
        rows = list(
            (
                await session.execute(
                    select(AdminAuditLog).where(AdminAuditLog.action == "service.edit")
                )
            ).scalars()
        )
    assert rows == []


async def test_delete_service(client):
    owner_id = await _bootstrap_user(client, 100, "owner")
    sid = await _create_service(owner_id)
    admin_init = await _make_admin(client)
    resp = await client.post(f"/api/admin/services/{sid}/delete", headers=auth_headers(admin_init))
    assert resp.status_code == 200
    async with async_session() as session:
        assert await session.get(Service, sid) is None


# ── Reviews ────────────────────────────────────────────────────────────────


async def test_create_review_as_admin(client):
    a_id = await _bootstrap_user(client, 200, "a")
    b_id = await _bootstrap_user(client, 201, "b")
    admin_init = await _make_admin(client)
    resp = await client.post(
        "/api/admin/reviews",
        json={
            "author_id": a_id,
            "target_id": b_id,
            "rating": 5,
            "text": "great",
        },
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["author_id"] == a_id
    assert body["target_id"] == b_id
    assert body["rating"] == 5


async def test_create_review_rejects_self_review(client):
    a_id = await _bootstrap_user(client, 200, "a")
    admin_init = await _make_admin(client)
    resp = await client.post(
        "/api/admin/reviews",
        json={"author_id": a_id, "target_id": a_id, "rating": 5, "text": ""},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 400


async def test_update_and_delete_review(client):
    a_id = await _bootstrap_user(client, 200, "a")
    b_id = await _bootstrap_user(client, 201, "b")
    admin_init = await _make_admin(client)
    create = await client.post(
        "/api/admin/reviews",
        json={"author_id": a_id, "target_id": b_id, "rating": 4, "text": "ok"},
        headers=auth_headers(admin_init),
    )
    rid = create.json()["id"]

    upd = await client.post(
        f"/api/admin/reviews/{rid}",
        json={"rating": 2, "text": "actually bad"},
        headers=auth_headers(admin_init),
    )
    assert upd.status_code == 200
    assert upd.json()["rating"] == 2
    assert upd.json()["text"] == "actually bad"

    rm = await client.post(f"/api/admin/reviews/{rid}/delete", headers=auth_headers(admin_init))
    assert rm.status_code == 200
    async with async_session() as session:
        assert await session.get(Review, rid) is None


# ── Comments ───────────────────────────────────────────────────────────────


async def _create_comment(author_id: int, service_id: int, text: str = "nice") -> int:
    async with async_session() as session:
        c = ServiceComment(service_id=service_id, author_id=author_id, text=text, rating=4)
        session.add(c)
        await session.commit()
        await session.refresh(c)
        return c.id


async def test_list_user_comments(client):
    author_id = await _bootstrap_user(client, 300, "author")
    owner_id = await _bootstrap_user(client, 301, "owner")
    sid = await _create_service(owner_id)
    cid = await _create_comment(author_id, sid, text="one")
    admin_init = await _make_admin(client)
    resp = await client.get(
        f"/api/admin/users/{author_id}/comments", headers=auth_headers(admin_init)
    )
    assert resp.status_code == 200
    assert any(c["id"] == cid for c in resp.json())


async def test_update_comment_text_and_rating(client):
    author_id = await _bootstrap_user(client, 300, "author")
    owner_id = await _bootstrap_user(client, 301, "owner")
    sid = await _create_service(owner_id)
    cid = await _create_comment(author_id, sid)
    admin_init = await _make_admin(client)
    resp = await client.post(
        f"/api/admin/comments/{cid}",
        json={"text": "edited", "rating": 1},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 200
    assert resp.json()["text"] == "edited"
    assert resp.json()["rating"] == 1


async def test_delete_comment(client):
    author_id = await _bootstrap_user(client, 300, "author")
    owner_id = await _bootstrap_user(client, 301, "owner")
    sid = await _create_service(owner_id)
    cid = await _create_comment(author_id, sid)
    admin_init = await _make_admin(client)
    resp = await client.post(f"/api/admin/comments/{cid}/delete", headers=auth_headers(admin_init))
    assert resp.status_code == 200
    async with async_session() as session:
        assert await session.get(ServiceComment, cid) is None
