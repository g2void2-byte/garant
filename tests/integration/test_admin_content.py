"""Admin content editing — services / reviews / comments."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import (
    AdminAuditLog,
    Category,
    Review,
    Service,
    ServiceComment,
    ServiceStatus,
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


async def _create_service(
    owner_id: int,
    *,
    title: str = "S",
    price: Decimal | int | str = 10,
    deposit: Decimal | int | str = 0,
    rating_manual: Decimal | None = None,
    status: ServiceStatus = ServiceStatus.active,
    ban_reason: str | None = None,
) -> int:
    async with async_session() as session:
        cat = (await session.execute(select(Category))).scalars().first()
        assert cat is not None
        service = Service(
            owner_id=owner_id,
            category_id=cat.id,
            title=title,
            description="desc",
            price=price,
            deposit=deposit,
            rating_manual=rating_manual,
            status=status,
            ban_reason=ban_reason,
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
    body = resp.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["page_size"] == 20
    ids = {s["id"] for s in body["items"]}
    assert s1 in ids and s2 in ids

    page2 = await client.get(
        f"/api/admin/users/{owner_id}/services?page=2&page_size=1",
        headers=auth_headers(admin_init),
    )
    assert page2.status_code == 200
    assert page2.json()["total"] == 2
    assert [s["id"] for s in page2.json()["items"]] == [s1]


async def test_update_service_changes_fields_and_writes_audit(client):
    owner_id = await _bootstrap_user(client, 100, "owner")
    sid = await _create_service(owner_id)
    admin_init = await _make_admin(client)
    resp = await client.post(
        f"/api/admin/services/{sid}",
        json={
            "title": "Updated",
            "price": "0.12345678",
            "deposit": "5.00000001",
            "deals_count": 7,
            "rating_manual": "4.5",
            "status": "paused",
        },
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "Updated"
    assert Decimal(str(body["price"])) == Decimal("0.12345678")
    assert Decimal(str(body["deposit"])) == Decimal("5.00000001")
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
    payload = rows[0].payload
    assert payload is not None
    assert payload["after"]["price"] == "0.12345678"
    assert payload["after"]["deposit"] == "5.00000001"
    assert payload["after"]["rating_manual"] == "4.5"


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


async def test_update_service_clears_rating_manual_with_explicit_null(client):
    owner_id = await _bootstrap_user(client, 100, "owner")
    sid = await _create_service(owner_id, rating_manual=Decimal("4.5"))
    admin_init = await _make_admin(client)

    resp = await client.post(
        f"/api/admin/services/{sid}",
        json={"rating_manual": None},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rating_manual"] is None

    async with async_session() as session:
        service = await session.get(Service, sid)
        assert service is not None
        assert service.rating_manual is None
        audit = (
            await session.execute(
                select(AdminAuditLog)
                .where(AdminAuditLog.action == "service.edit")
                .order_by(AdminAuditLog.id.desc())
                .limit(1)
            )
        ).scalar_one()
    assert audit.payload is not None
    assert Decimal(audit.payload["before"]["rating_manual"]) == Decimal("4.50")
    assert audit.payload["after"]["rating_manual"] is None


async def test_update_service_rejects_explicit_null_for_non_nullable_fields(client):
    owner_id = await _bootstrap_user(client, 100, "owner")
    sid = await _create_service(owner_id, title="Same")
    admin_init = await _make_admin(client)

    resp = await client.post(
        f"/api/admin/services/{sid}",
        json={"title": None},
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


async def test_update_service_clears_ban_reason_with_explicit_null(client):
    owner_id = await _bootstrap_user(client, 100, "owner")
    sid = await _create_service(
        owner_id,
        status=ServiceStatus.banned,
        ban_reason="old reason",
    )
    admin_init = await _make_admin(client)

    resp = await client.post(
        f"/api/admin/services/{sid}",
        json={"ban_reason": None},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "banned"
    assert body["ban_reason"] is None

    async with async_session() as session:
        service = await session.get(Service, sid)
        assert service is not None
        assert service.ban_reason is None
        audit = (
            await session.execute(
                select(AdminAuditLog)
                .where(AdminAuditLog.action == "service.edit")
                .order_by(AdminAuditLog.id.desc())
                .limit(1)
            )
        ).scalar_one()
    assert audit.payload is not None
    assert audit.payload["before"]["ban_reason"] == "old reason"
    assert audit.payload["after"]["ban_reason"] is None


async def test_update_service_unban_clears_stale_ban_reason(client):
    owner_id = await _bootstrap_user(client, 100, "owner")
    sid = await _create_service(
        owner_id,
        status=ServiceStatus.banned,
        ban_reason="policy issue",
    )
    admin_init = await _make_admin(client)

    resp = await client.post(
        f"/api/admin/services/{sid}",
        json={"status": "active"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "active"
    assert body["ban_reason"] is None

    async with async_session() as session:
        service = await session.get(Service, sid)
        assert service is not None
        assert service.status == ServiceStatus.active
        assert service.ban_reason is None
        audit = (
            await session.execute(
                select(AdminAuditLog)
                .where(AdminAuditLog.action == "service.edit")
                .order_by(AdminAuditLog.id.desc())
                .limit(1)
            )
        ).scalar_one()
    assert audit.payload is not None
    assert audit.payload["after"]["status"] == "active"
    assert audit.payload["before"]["ban_reason"] == "policy issue"
    assert audit.payload["after"]["ban_reason"] is None


async def test_delete_service(client):
    owner_id = await _bootstrap_user(client, 100, "owner")
    sid = await _create_service(
        owner_id,
        price=Decimal("0.12345678"),
        deposit=Decimal("5.00000001"),
        rating_manual=Decimal("4.5"),
    )
    admin_init = await _make_admin(client)
    resp = await client.post(
        f"/api/admin/services/{sid}/delete",
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200
    async with async_session() as session:
        assert await session.get(Service, sid) is None
        audit = (
            await session.execute(
                select(AdminAuditLog).where(AdminAuditLog.action == "service.delete")
            )
        ).scalar_one()
    assert audit.payload is not None
    assert audit.payload["price"] == "0.12345678"
    assert audit.payload["deposit"] == "5.00000001"
    assert isinstance(audit.payload["rating_manual"], str)
    assert Decimal(audit.payload["rating_manual"]) == Decimal("4.5")


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


async def test_update_review_rejects_missing_text(client):
    a_id = await _bootstrap_user(client, 200, "a")
    b_id = await _bootstrap_user(client, 201, "b")
    admin_init = await _make_admin(client)
    create = await client.post(
        "/api/admin/reviews",
        json={"author_id": a_id, "target_id": b_id, "rating": 4, "text": "keep me"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert create.status_code == 201, create.text
    rid = create.json()["id"]

    resp = await client.post(
        f"/api/admin/reviews/{rid}",
        json={"rating": 2},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 422, resp.text

    async with async_session() as session:
        review = await session.get(Review, rid)
        assert review is not None
        assert review.text == "keep me"


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
    body = resp.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert any(c["id"] == cid for c in body["items"])


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


async def test_update_comment_clears_rating_with_explicit_null(client):
    author_id = await _bootstrap_user(client, 300, "author")
    owner_id = await _bootstrap_user(client, 301, "owner")
    sid = await _create_service(owner_id)
    cid = await _create_comment(author_id, sid)
    admin_init = await _make_admin(client)

    resp = await client.post(
        f"/api/admin/comments/{cid}",
        json={"rating": None},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rating"] is None

    async with async_session() as session:
        comment = await session.get(ServiceComment, cid)
        assert comment is not None
        assert comment.rating is None
        audit = (
            await session.execute(
                select(AdminAuditLog)
                .where(AdminAuditLog.action == "comment.edit")
                .order_by(AdminAuditLog.id.desc())
                .limit(1)
            )
        ).scalar_one()
    assert audit.payload is not None
    assert audit.payload["before"]["rating"] == 4
    assert audit.payload["after"]["rating"] is None


async def test_update_comment_rejects_explicit_null_text(client):
    author_id = await _bootstrap_user(client, 300, "author")
    owner_id = await _bootstrap_user(client, 301, "owner")
    sid = await _create_service(owner_id)
    cid = await _create_comment(author_id, sid)
    admin_init = await _make_admin(client)

    resp = await client.post(
        f"/api/admin/comments/{cid}",
        json={"text": None},
        headers=with_totp(auth_headers(admin_init)),
    )

    assert resp.status_code == 422


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
    assert resp.json()["service_id"] == sid
    assert resp.json()["author_id"] == author_id
    async with async_session() as session:
        assert await session.get(ServiceComment, cid) is None
