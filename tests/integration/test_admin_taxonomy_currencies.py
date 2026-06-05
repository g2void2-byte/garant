"""I-11 \u2014 coverage gap-fill for the ``/api/admin/currencies`` upsert.

``test_admin_misc.py::test_taxonomy_currencies_upsert`` already covers
the *create* branch. The update branch \u2014 hitting the same route
again for an existing currency \u2014 had no test, which is risky because
the handler does very different things in each case (partial
incremental update of fields the caller actually sent, audit log
payload with a ``before`` snapshot, no-op safety when nothing
changed). RBAC + the no-op /api/admin/users path also got a smoke
test for symmetry.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import AdminAuditLog, Currency, User, UserBalance
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


async def test_currency_update_partial_fields_keeps_unset_values(client):
    """A PUT carrying only ``min_deposit`` must update *that* column
    and leave the other settable columns alone. This is the core
    safety property of the partial-update semantics."""
    admin_init, _ = await _make_admin(client, tg=1)

    # Step 1 \u2014 create the row.
    resp = await client.put(
        "/api/admin/currencies",
        json={
            "code": "JET1",
            "name": "Jeton",
            "network": "TON",
            "decimals": 8,
            "min_deposit": 0.5,
            "min_withdraw": 0.5,
            "is_active": True,
            "sort_order": 7,
        },
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["code"] == "JET1"
    assert created["min_deposit"] == 0.5
    assert created["sort_order"] == 7

    # Step 2 \u2014 partial update: only min_deposit changes.
    resp = await client.put(
        "/api/admin/currencies",
        json={"code": "JET1", "min_deposit": 1.25},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    after = resp.json()
    assert after["code"] == "JET1"
    assert after["min_deposit"] == 1.25
    # Every other field must have been preserved.
    assert after["name"] == "Jeton"
    assert after["network"] == "TON"
    assert after["decimals"] == 8
    assert after["min_withdraw"] == 0.5
    assert after["is_active"] is True
    assert after["sort_order"] == 7


async def test_currency_update_can_deactivate(client):
    """Flipping ``is_active`` to False on an existing row must persist
    and must surface in the response body (so the admin UI can render
    the deactivated state immediately without re-fetching the list)."""
    admin_init, _ = await _make_admin(client, tg=1)

    resp = await client.put(
        "/api/admin/currencies",
        json={"code": "JET2", "name": "Jeton 2", "is_active": True},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is True

    resp = await client.put(
        "/api/admin/currencies",
        json={"code": "JET2", "is_active": False},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is False

    async with async_session() as session:
        row = (await session.execute(select(Currency).where(Currency.code == "JET2"))).scalar_one()
        assert row.is_active is False


async def test_currency_update_writes_audit_payload_with_before(client):
    """The audit log entry for an update must include a ``before``
    snapshot of the row so a security review can diff what changed.
    The first (create) call writes ``before=None`` \u2014 we check both
    here so the test pins the contract end-to-end."""
    admin_init, admin_id = await _make_admin(client, tg=1)

    # Create
    resp = await client.put(
        "/api/admin/currencies",
        json={
            "code": "JET3",
            "name": "Jeton 3",
            "decimals": 4,
            "min_deposit": "0.12345678",
            "min_withdraw": "5.00000001",
            "is_active": True,
        },
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text

    # Update (changes name + min_deposit).
    resp = await client.put(
        "/api/admin/currencies",
        json={"code": "JET3", "name": "Jeton III", "min_deposit": "0.87654321"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text

    async with async_session() as session:
        logs = (
            (
                await session.execute(
                    select(AdminAuditLog)
                    .where(AdminAuditLog.actor_id == admin_id)
                    .where(AdminAuditLog.target_type == "currency")
                    .order_by(AdminAuditLog.id)
                )
            )
            .scalars()
            .all()
        )
    actions = [r.action for r in logs]
    assert "currency.create" in actions
    assert "currency.update" in actions

    create_payload = next(r.payload for r in logs if r.action == "currency.create")
    update_payload = next(r.payload for r in logs if r.action == "currency.update")
    assert create_payload["before"] is None
    assert create_payload["after"]["min_deposit"] == "0.12345678"
    assert create_payload["after"]["min_withdraw"] == "5.00000001"
    assert update_payload["before"] is not None
    assert update_payload["before"]["name"] == "Jeton 3"
    assert update_payload["before"]["min_deposit"] == "0.12345678"
    assert update_payload["before"]["min_withdraw"] == "5.00000001"
    assert update_payload["after"]["name"] == "Jeton III"
    assert update_payload["after"]["min_deposit"] == "0.87654321"
    assert update_payload["after"]["min_withdraw"] == "5.00000001"


async def test_currency_update_requires_admin(client):
    """A non-admin user hitting ``PUT /api/admin/currencies`` must
    receive 403, even with valid initData. The currency upsert is a
    TOTP-gated route, so the assertion really exercises the RBAC dep
    rather than the TOTP gate \u2014 a non-admin should bounce before
    any 2FA check."""
    init = signed_init_data(99, "regular")
    await _bootstrap(client, tg_user_id=99, username="regular")
    resp = await client.put(
        "/api/admin/currencies",
        json={"code": "JET4", "name": "no-go"},
        headers=auth_headers(init),
    )
    assert resp.status_code == 403


async def test_currency_create_then_update_does_not_duplicate_row(client):
    """The upsert must be idempotent on ``code``: a second create-shape
    PUT for the same code must MUTATE the existing row, not insert
    a duplicate (which would violate the unique-on-code index but is
    worth pinning with a behaviour test)."""
    admin_init, _ = await _make_admin(client, tg=1)

    for _ in range(2):
        resp = await client.put(
            "/api/admin/currencies",
            json={
                "code": "JET5",
                "name": "Jeton 5",
                "decimals": 2,
                "min_deposit": 1.0,
                "min_withdraw": 1.0,
                "is_active": True,
            },
            headers=with_totp(auth_headers(admin_init)),
        )
        assert resp.status_code == 200, resp.text

    async with async_session() as session:
        rows = (
            (await session.execute(select(Currency).where(Currency.code == "JET5"))).scalars().all()
        )
    assert len(rows) == 1


# ── DELETE /api/admin/currencies/{id} (audit §3.4) ─────


async def test_currency_delete_removes_unreferenced_row(client):
    """Audit §3.4 — the new DELETE endpoint hard-deletes a currency
    that nothing references and writes a ``currency.delete`` audit
    log entry."""
    admin_init, admin_id = await _make_admin(client, tg=1)

    resp = await client.put(
        "/api/admin/currencies",
        json={
            "code": "DEL1",
            "name": "Doomed",
            "network": "TON",
            "icon_url": "https://example.test/del1.svg",
            "decimals": 8,
            "min_deposit": "0.12345678",
            "min_withdraw": "5.00000001",
            "address_regex": "^DEL[0-9]+$",
            "kind": "crypto",
        },
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    currency_id = resp.json()["id"]

    resp = await client.delete(
        f"/api/admin/currencies/{currency_id}",
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}

    async with async_session() as session:
        row = (
            await session.execute(select(Currency).where(Currency.id == currency_id))
        ).scalar_one_or_none()
        assert row is None

        logs = (
            (
                await session.execute(
                    select(AdminAuditLog)
                    .where(AdminAuditLog.actor_id == admin_id)
                    .where(AdminAuditLog.target_type == "currency")
                    .where(AdminAuditLog.action == "currency.delete")
                )
            )
            .scalars()
            .all()
        )
    assert len(logs) == 1
    payload = logs[0].payload
    assert payload["code"] == "DEL1"
    assert payload["network"] == "TON"
    assert payload["icon_url"] == "https://example.test/del1.svg"
    assert payload["min_deposit"] == "0.12345678"
    assert payload["min_withdraw"] == "5.00000001"
    assert payload["address_regex"] == "^DEL[0-9]+$"
    assert payload["kind"] == "crypto"


async def test_currency_delete_missing_returns_404(client):
    admin_init, _ = await _make_admin(client, tg=1)
    resp = await client.delete(
        "/api/admin/currencies/999999",
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 404


async def test_currency_delete_blocked_when_referenced(client):
    """Audit §3.4 — the DELETE endpoint must refuse to orphan a FK.
    Seed a ``user_balances`` row pointing at the currency and assert
    we get a 409 with a ``referenced_by`` list naming the blocker."""
    admin_init, _ = await _make_admin(client, tg=1)
    user_id = await _bootstrap(client, tg_user_id=42, username="hodler")

    resp = await client.put(
        "/api/admin/currencies",
        json={"code": "REF1", "name": "Referenced"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    currency_id = resp.json()["id"]

    async with async_session() as session:
        session.add(
            UserBalance(
                user_id=user_id,
                currency_id=currency_id,
                amount=Decimal("1.0"),
                locked=Decimal("0.0"),
            )
        )
        await session.commit()

    resp = await client.delete(
        f"/api/admin/currencies/{currency_id}",
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["detail"] == "К валюте привязаны данные, удаление невозможно"
    assert "user_balances" in detail["referenced_by"]

    async with async_session() as session:
        row = (
            await session.execute(select(Currency).where(Currency.id == currency_id))
        ).scalar_one_or_none()
        assert row is not None


async def test_currency_delete_requires_admin(client):
    """A non-admin caller hitting the DELETE route must be rejected
    by RBAC before any 2FA / state check runs."""
    admin_init, _ = await _make_admin(client, tg=1)
    init = signed_init_data(99, "regular")
    await _bootstrap(client, tg_user_id=99, username="regular")

    resp = await client.put(
        "/api/admin/currencies",
        json={"code": "RBAC", "name": "rbac"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200
    currency_id = resp.json()["id"]

    resp = await client.delete(
        f"/api/admin/currencies/{currency_id}",
        headers=auth_headers(init),
    )
    assert resp.status_code == 403
