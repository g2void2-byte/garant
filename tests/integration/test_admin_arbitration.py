"""Admin arbitration queue — `/api/admin/arbitration`."""

from __future__ import annotations

from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import AdminAuditLog, Deal, DealStatus, User
from tests.helpers import (
    auth_headers,
    credit_balance,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
    with_totp,
)


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


async def _make_arbiter(client, tg_id: int, username: str) -> tuple[str, int]:
    init = signed_init_data(tg_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    uid = resp.json()["id"]
    async with async_session() as session:
        user = await session.get(User, uid)
        assert user is not None
        user.is_arbiter = True
        await session.commit()
    return init, uid


async def _make_arbitration_deal(client) -> int:
    """Spin up a fresh deal and force it into arbitration via the API."""
    buyer_init = signed_init_data(2001, "buyer2")
    seller_init = signed_init_data(2002, "seller2")
    buyer_pin = await setup_pin(client, buyer_init)
    seller_pin = await setup_pin(client, seller_init)
    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 2001)
        await credit_balance(session, buyer_id, "USDT", 1000)

    create = await client.post(
        "/api/deals",
        json={
            "counterparty": "seller2",
            "role": "buyer",
            "amount": 100,
            "description": "",
            "currency_code": "USDT",
        },
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    deal_id = create.json()["id"]
    await client.post(
        f"/api/deals/{deal_id}/accept",
        headers={**auth_headers(seller_init), "X-Pin-Token": seller_pin},
    )
    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        deal.status = DealStatus.arbitration
        await session.commit()
    return deal_id


# ── RBAC ───────────────────────────────────────────────────────────────────


async def test_arbitration_queue_forbidden_for_non_staff(client):
    init = signed_init_data(10, "alice")
    await client.get("/api/me", headers=auth_headers(init))
    resp = await client.get("/api/admin/arbitration", headers=auth_headers(init))
    assert resp.status_code == 403


async def test_arbitration_queue_allowed_for_arbiter(client):
    init, _ = await _make_arbiter(client, 11, "arb")
    resp = await client.get("/api/admin/arbitration", headers=auth_headers(init))
    assert resp.status_code == 200


# ── Counters + queue switching ─────────────────────────────────────────────


async def test_arbitration_queue_new_lists_unassigned(client):
    deal_id = await _make_arbitration_deal(client)
    admin_init = await _make_admin(client)
    resp = await client.get("/api/admin/arbitration?queue=new", headers=auth_headers(admin_init))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert any(item["id"] == deal_id for item in body["items"])
    assert body["counters"]["new"] >= 1
    assert body["queue"] == "new"


async def test_arbitration_queue_in_progress_after_assignment(client):
    deal_id = await _make_arbitration_deal(client)
    admin_init = await _make_admin(client)
    # assign via deals endpoint to be uniform
    arb_init, arb_id = await _make_arbiter(client, 11, "arb")
    await client.post(
        f"/api/admin/deals/{deal_id}/assign-arbiter",
        json={"arbiter_id": arb_id},
        headers=with_totp(auth_headers(admin_init)),
    )
    resp = await client.get(
        "/api/admin/arbitration?queue=in_progress", headers=auth_headers(admin_init)
    )
    assert resp.status_code == 200
    assert any(item["id"] == deal_id for item in resp.json()["items"])


# ── Claim ───────────────────────────────────────────────────────────────────


async def test_arbitration_claim_self_assigns_arbiter(client):
    deal_id = await _make_arbitration_deal(client)
    arb_init, arb_id = await _make_arbiter(client, 11, "arb")
    resp = await client.post(
        f"/api/admin/arbitration/{deal_id}/claim",
        headers=auth_headers(arb_init),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["claimed"] is True
    assert body["arbiter_id"] == arb_id
    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        assert deal.arbitration_resolved_by == arb_id


async def test_arbitration_claim_conflict_when_already_claimed(client):
    deal_id = await _make_arbitration_deal(client)
    arb_a_init, _ = await _make_arbiter(client, 11, "arb_a")
    arb_b_init, _ = await _make_arbiter(client, 12, "arb_b")
    r1 = await client.post(
        f"/api/admin/arbitration/{deal_id}/claim",
        headers=auth_headers(arb_a_init),
    )
    assert r1.status_code == 200
    r2 = await client.post(
        f"/api/admin/arbitration/{deal_id}/claim",
        headers=auth_headers(arb_b_init),
    )
    assert r2.status_code == 409


async def test_arbitration_claim_writes_audit_row(client):
    deal_id = await _make_arbitration_deal(client)
    arb_init, _ = await _make_arbiter(client, 11, "arb")
    await client.post(
        f"/api/admin/arbitration/{deal_id}/claim",
        headers=auth_headers(arb_init),
    )
    async with async_session() as session:
        rows = list(
            (
                await session.execute(
                    select(AdminAuditLog).where(AdminAuditLog.action == "arbitration.claim")
                )
            ).scalars()
        )
    assert len(rows) == 1
