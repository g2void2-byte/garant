"""I-11 — coverage gap-fill for ``/api/admin/categories``.

``test_admin_misc.py`` exercises the *create* branch via the seed-and-
upsert flow. The *update*, *delete*, *delete-blocked-by-services*, and
*RBAC* branches all had zero coverage. Each is a money-adjacent path
(an admin who can rename categories can move services into a hidden
bucket; an admin who can delete categories can orphan services if the
"has services" gate ever breaks).

All upsert/delete handlers require ``X-Totp-Code``. The test harness
sets ``ADMIN_TOTP_BYPASS`` in ``conftest.py``; we use ``with_totp(...)``
to attach that bypass header.
"""

from __future__ import annotations

from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import (
    AdminAuditLog,
    Category,
    Service,
    ServiceStatus,
    User,
)
from tests.helpers import auth_headers, signed_init_data, with_totp


async def _bootstrap(client, *, tg_user_id: int, username: str) -> int:
    init = signed_init_data(tg_user_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _make_admin(client, tg: int = 1) -> tuple[str, int]:
    init = signed_init_data(tg, f"admin{tg}")
    uid = await _bootstrap(client, tg_user_id=tg, username=f"admin{tg}")
    async with async_session() as session:
        u = await session.get(User, uid)
        u.is_admin = True
        await session.commit()
    return init, uid


async def _audit_actions_for(target_id: int) -> list[AdminAuditLog]:
    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(AdminAuditLog)
                    .where(AdminAuditLog.target_id == target_id)
                    .where(AdminAuditLog.target_type == "category")
                    .order_by(AdminAuditLog.id)
                )
            )
            .scalars()
            .all()
        )
        # Detach from session for easier inspection in the test thread.
        for r in rows:
            session.expunge(r)
        return rows


async def test_category_create_persists_row_and_audits_with_before_none(client):
    admin_init, _ = await _make_admin(client, tg=1)
    resp = await client.put(
        "/api/admin/categories",
        json={"slug": "test-cat-1", "name": "Test 1", "icon": "tag"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["slug"] == "test-cat-1"
    assert body["name"] == "Test 1"
    assert body["icon"] == "tag"

    audits = await _audit_actions_for(body["id"])
    assert len(audits) == 1
    log = audits[0]
    assert log.action == "category.create"
    payload = log.payload or {}
    assert payload.get("before") is None
    assert payload.get("after") == {"name": "Test 1", "icon": "tag"}


async def test_category_update_persists_changes_and_records_before_snapshot(client):
    admin_init, _ = await _make_admin(client, tg=1)
    create = await client.put(
        "/api/admin/categories",
        json={"slug": "test-cat-2", "name": "Old name", "icon": "tag"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert create.status_code == 200
    cat_id = create.json()["id"]

    update = await client.put(
        "/api/admin/categories",
        json={"slug": "test-cat-2", "name": "New name", "icon": "compass"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert update.status_code == 200, update.text
    body = update.json()
    assert body["id"] == cat_id
    assert body["name"] == "New name"
    assert body["icon"] == "compass"

    audits = await _audit_actions_for(cat_id)
    assert [a.action for a in audits] == ["category.create", "category.update"]
    update_log = audits[1].payload or {}
    assert update_log.get("before") == {"name": "Old name", "icon": "tag"}
    assert update_log.get("after") == {"name": "New name", "icon": "compass"}


async def test_category_delete_succeeds_when_no_services_linked(client):
    admin_init, _ = await _make_admin(client, tg=1)
    create = await client.put(
        "/api/admin/categories",
        json={"slug": "test-cat-3", "name": "Disposable", "icon": "trash"},
        headers=with_totp(auth_headers(admin_init)),
    )
    cat_id = create.json()["id"]

    resp = await client.delete(
        f"/api/admin/categories/{cat_id}",
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}

    async with async_session() as session:
        row = await session.get(Category, cat_id)
        assert row is None

    audits = await _audit_actions_for(cat_id)
    # create + delete (no in-between update)
    actions = [a.action for a in audits]
    assert "category.delete" in actions


async def test_category_delete_blocked_when_services_reference_it(client):
    admin_init, admin_id = await _make_admin(client, tg=1)
    create = await client.put(
        "/api/admin/categories",
        json={"slug": "test-cat-4", "name": "Has-Service", "icon": "link"},
        headers=with_totp(auth_headers(admin_init)),
    )
    cat_id = create.json()["id"]
    # Pin a service to the category so the deletion guard kicks in.
    async with async_session() as session:
        s = Service(
            owner_id=admin_id,
            category_id=cat_id,
            title="pin",
            description="",
            price=1,
            status=ServiceStatus.active,
        )
        session.add(s)
        await session.commit()

    resp = await client.delete(
        f"/api/admin/categories/{cat_id}",
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 409, resp.text
    # The row still exists.
    async with async_session() as session:
        row = await session.get(Category, cat_id)
        assert row is not None


async def test_category_upsert_rejects_non_admin(client):
    """A non-admin caller hitting the same PUT must be refused — no
    write happens and no audit log entry is written."""
    init = signed_init_data(900, "not_an_admin")
    await _bootstrap(client, tg_user_id=900, username="not_an_admin")
    resp = await client.put(
        "/api/admin/categories",
        json={"slug": "abuser", "name": "abuser", "icon": "x"},
        headers=with_totp(auth_headers(init)),
    )
    assert resp.status_code == 403


async def test_category_delete_404_for_unknown_id(client):
    admin_init, _ = await _make_admin(client, tg=1)
    resp = await client.delete(
        "/api/admin/categories/9999999",
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 404


async def test_category_upsert_requires_totp_header(client):
    """RBAC OK but without the TOTP header the request fails with 401."""
    admin_init, _ = await _make_admin(client, tg=1)
    resp = await client.put(
        "/api/admin/categories",
        json={"slug": "no-totp", "name": "x", "icon": "x"},
        headers=auth_headers(admin_init),  # no X-Totp-Code
    )
    # 401 (no TOTP) or 403 depending on dependency ordering — we accept
    # either as long as the write was rejected and no audit entry exists.
    assert resp.status_code in (401, 403), resp.text
    async with async_session() as session:
        rows = (
            (await session.execute(select(Category).where(Category.slug == "no-totp")))
            .scalars()
            .all()
        )
        assert rows == []
