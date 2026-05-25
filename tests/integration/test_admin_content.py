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
from tests.helpers import auth_headers, signed_init_data, with_totp


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
        headers=with_totp(auth_headers(admin_init)),
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
        headers=with_totp(auth_headers(admin_init)),
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
        headers=with_totp(auth_headers(admin_init)),
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
    resp = await client.post(
        f"/api/admin/services/{sid}/delete",
        headers=with_totp(auth_headers(admin_init)),
    )
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
        headers=with_totp(auth_headers(admin_init)),
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
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 400


async def test_update_and_delete_review(client):
    a_id = await _bootstrap_user(client, 200, "a")
    b_id = await _bootstrap_user(client, 201, "b")
    admin_init = await _make_admin(client)
    create = await client.post(
        "/api/admin/reviews",
        json={"author_id": a_id, "target_id": b_id, "rating": 4, "text": "ok"},
        headers=with_totp(auth_headers(admin_init)),
    )
    rid = create.json()["id"]

    upd = await client.post(
        f"/api/admin/reviews/{rid}",
        json={"rating": 2, "text": "actually bad"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert upd.status_code == 200
    assert upd.json()["rating"] == 2
    assert upd.json()["text"] == "actually bad"

    rm = await client.post(
        f"/api/admin/reviews/{rid}/delete",
        headers=with_totp(auth_headers(admin_init)),
    )
    assert rm.status_code == 200
    async with async_session() as session:
        assert await session.get(Review, rid) is None


async def test_admin_review_create_update_delete_recomputes_target_counters(client):
    """Item 14 — admin review CRUD has to keep ``target.good`` /
    ``target.bad`` in sync with the ``reviews`` table.

    Pre-fix the admin endpoints wrote the ``reviews`` row but never
    touched ``good`` / ``bad`` (only ``services.post_review`` did).
    Result: an admin-created review was invisible on the affected
    user's profile because ``reviews_count = good + bad`` stayed
    unchanged.
    """
    a_id = await _bootstrap_user(client, 200, "a")
    b_id = await _bootstrap_user(client, 201, "b")
    admin_init = await _make_admin(client)

    # rating=5 ⇒ a "good" review.
    create = await client.post(
        "/api/admin/reviews",
        json={"author_id": a_id, "target_id": b_id, "rating": 5, "text": "great"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert create.status_code == 201, create.text
    rid = create.json()["id"]

    async with async_session() as session:
        target = await session.get(User, b_id)
        assert target is not None
        assert target.good == 1
        assert target.bad == 0

    # rating=5 → rating=2 ⇒ "good" decrements, "bad" increments.
    upd = await client.post(
        f"/api/admin/reviews/{rid}",
        json={"rating": 2, "text": "not actually that great"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert upd.status_code == 200, upd.text

    async with async_session() as session:
        target = await session.get(User, b_id)
        assert target is not None
        assert target.good == 0
        assert target.bad == 1

    rm = await client.post(
        f"/api/admin/reviews/{rid}/delete",
        headers=with_totp(auth_headers(admin_init)),
    )
    assert rm.status_code == 200, rm.text

    async with async_session() as session:
        target = await session.get(User, b_id)
        assert target is not None
        assert target.good == 0
        assert target.bad == 0


async def test_admin_review_create_surfaces_on_user_profile(client):
    """End-to-end item 14 — after admin creates a review on B, the
    public ``GET /api/users/<username>`` for B reflects the bumped
    ``reviews_count`` and a non-zero ``good``. This is the user-
    visible bug ("в админке вижу, на профиле нет") collapsed into a
    single integration assertion.
    """
    a_id = await _bootstrap_user(client, 200, "a")
    b_id = await _bootstrap_user(client, 201, "b")
    admin_init = await _make_admin(client)

    create = await client.post(
        "/api/admin/reviews",
        json={"author_id": a_id, "target_id": b_id, "rating": 5, "text": "great"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert create.status_code == 201, create.text

    # Sanity: ``GET /api/users/b`` is the public profile fetch used
    # by the TMA to render somebody else's stats grid.
    resp = await client.get("/api/users/b", headers=auth_headers(admin_init))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == b_id
    assert body["good"] == 1
    assert body["bad"] == 0
    assert body["reviews_count"] == 1


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
        headers=with_totp(auth_headers(admin_init)),
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
    resp = await client.post(
        f"/api/admin/comments/{cid}/delete",
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200
    async with async_session() as session:
        assert await session.get(ServiceComment, cid) is None
