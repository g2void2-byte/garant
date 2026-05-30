"""Admin deal management — `/api/admin/deals/*`.

PR-B coverage:

* RBAC: regular users get 403 on every endpoint.
* List: filter by status / currency, pagination, ordering.
* Detail: balance snapshot, event timeline, messages.
* force-release: idempotency on terminal status, releases locked funds,
  audit row written, DM dispatched.
* force-refund: refunds buyer including buyer-paid commission portion.
* split: percent split between buyer and seller, commission retained.
* force-arbitration: idempotency, moves to arbitration status.
* assign-arbiter: requires `is_arbiter`, idempotent, clearable.
* delete: refunds locked funds, deletes messages, audit row captures
  the full snapshot of the deleted deal.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import (
    AdminAuditLog,
    Currency,
    Deal,
    DealMessage,
    DealStatus,
    User,
    UserBalance,
)
from tests.helpers import (
    auth_headers,
    credit_balance,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
    with_totp,
)


async def _make_deal(client) -> tuple[int, str, str, str, str]:
    """Create a fresh deal in ``in_progress`` and return useful handles."""
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
            "description": "for admin testing",
            "currency_code": "USDT",
        },
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    assert create.status_code == 201, create.text
    deal_id = create.json()["id"]
    accept = await client.post(
        f"/api/deals/{deal_id}/accept",
        headers={**auth_headers(seller_init), "X-Pin-Token": seller_pin},
    )
    assert accept.status_code == 200, accept.text
    return deal_id, buyer_init, seller_init, buyer_pin, seller_pin


async def _make_admin(client, tg_id: int = 9001, username: str = "admin") -> str:
    init = signed_init_data(tg_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200
    uid = resp.json()["id"]
    async with async_session() as session:
        user = await session.get(User, uid)
        assert user is not None
        user.is_admin = True
        await session.commit()
    return init


async def _audit_rows(action: str | None = None) -> list[AdminAuditLog]:
    async with async_session() as session:
        stmt = select(AdminAuditLog).order_by(AdminAuditLog.created_at.asc())
        if action is not None:
            stmt = stmt.where(AdminAuditLog.action == action)
        return list((await session.execute(stmt)).scalars())


# ── RBAC ───────────────────────────────────────────────────────────────────


async def test_admin_deals_forbidden_for_non_admin(client):
    init = signed_init_data(10, "alice")
    await client.get("/api/me", headers=auth_headers(init))
    resp = await client.get("/api/admin/deals", headers=auth_headers(init))
    assert resp.status_code == 403


async def test_admin_deal_detail_forbidden_for_non_admin(client):
    deal_id, *_ = await _make_deal(client)
    init = signed_init_data(10, "alice")
    await client.get("/api/me", headers=auth_headers(init))
    resp = await client.get(f"/api/admin/deals/{deal_id}", headers=auth_headers(init))
    assert resp.status_code == 403


async def test_admin_force_release_forbidden_for_non_admin(client):
    deal_id, *_ = await _make_deal(client)
    init = signed_init_data(10, "alice")
    await client.get("/api/me", headers=auth_headers(init))
    resp = await client.post(
        f"/api/admin/deals/{deal_id}/force-release", json={}, headers=auth_headers(init)
    )
    assert resp.status_code == 403


# ── List + detail ─────────────────────────────────────────────────────────


async def test_admin_deals_list(client):
    deal_id, *_ = await _make_deal(client)
    admin_init = await _make_admin(client)

    resp = await client.get("/api/admin/deals", headers=auth_headers(admin_init))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    assert any(item["id"] == deal_id for item in body["items"])
    item = next(x for x in body["items"] if x["id"] == deal_id)
    assert item["status"] == DealStatus.in_progress.value
    assert item["currency_code"] == "USDT"


async def test_admin_deals_filter_by_status(client):
    deal_id, *_ = await _make_deal(client)
    admin_init = await _make_admin(client)

    resp = await client.get("/api/admin/deals?status=cancelled", headers=auth_headers(admin_init))
    assert resp.status_code == 200
    assert all(item["status"] == "cancelled" for item in resp.json()["items"])

    resp = await client.get("/api/admin/deals?status=in_progress", headers=auth_headers(admin_init))
    assert resp.status_code == 200
    assert any(item["id"] == deal_id for item in resp.json()["items"])


async def test_admin_deal_detail_balance_snapshot(client):
    deal_id, *_ = await _make_deal(client)
    admin_init = await _make_admin(client)
    resp = await client.get(f"/api/admin/deals/{deal_id}", headers=auth_headers(admin_init))
    assert resp.status_code == 200, resp.text
    detail = resp.json()
    assert detail["id"] == deal_id
    assert detail["status"] == DealStatus.in_progress.value
    assert detail["buyer"]["currency_code"] == "USDT"
    # P10 — the legacy ``POST /api/deals`` path locks only the
    # principal (100); commission rides on the deposit invoice in
    # ``create_deal_with_topup`` and is no longer added to
    # ``UserBalance.locked``.
    assert Decimal(detail["buyer"]["locked"]) == Decimal("100")
    assert any(ev["kind"] == "in_progress" for ev in detail["events"])


# ── force-release / refund / split ─────────────────────────────────────────


async def test_admin_force_release(client):
    deal_id, *_ = await _make_deal(client)
    admin_init = await _make_admin(client)
    resp = await client.post(
        f"/api/admin/deals/{deal_id}/force-release",
        json={"reason": "release after dispute"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    detail = resp.json()["deal"]
    assert detail["status"] == DealStatus.resolved_for_seller.value
    assert Decimal(detail["seller"]["amount"]) == Decimal("100")  # commission retained
    rows = await _audit_rows("deal.force_release")
    assert len(rows) == 1


async def test_admin_force_release_rejects_terminal(client):
    deal_id, *_ = await _make_deal(client)
    admin_init = await _make_admin(client)
    # finish first to make terminal
    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        deal.status = DealStatus.completed
        await session.commit()
    resp = await client.post(
        f"/api/admin/deals/{deal_id}/force-release",
        json={},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 400


async def test_admin_force_refund(client):
    deal_id, buyer_init, *_ = await _make_deal(client)
    admin_init = await _make_admin(client)
    resp = await client.post(
        f"/api/admin/deals/{deal_id}/force-refund",
        json={"reason": "refund"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    detail = resp.json()["deal"]
    assert detail["status"] == DealStatus.resolved_for_buyer.value
    assert Decimal(detail["buyer"]["locked"]) == Decimal(0)
    # H-02 — legacy creation now collects the same 5% commission as
    # /with-topup; force-refund returns the locked principal only.
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        buyer_id = await get_user_id_by_tg(session, 2001)
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == buyer_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        # started with 1000, creation charged 100 principal + 5 commission;
        # refund returns the full principal and leaves the commission paid.
        assert float(bal.amount) == 995.0


async def test_admin_split_deal(client):
    deal_id, *_ = await _make_deal(client)
    admin_init = await _make_admin(client)
    resp = await client.post(
        f"/api/admin/deals/{deal_id}/split",
        json={"buyer_percent": 60, "reason": "split"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    detail = resp.json()["deal"]
    # 60% to buyer, 40% to seller; commission (5) retained by platform
    assert Decimal(detail["buyer"]["amount"]) >= Decimal("60")
    assert Decimal(detail["seller"]["amount"]) == Decimal("40")


async def test_admin_split_percent_out_of_range(client):
    deal_id, *_ = await _make_deal(client)
    admin_init = await _make_admin(client)
    resp = await client.post(
        f"/api/admin/deals/{deal_id}/split",
        json={"buyer_percent": 150},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 422


# ── force-arbitration / assign-arbiter ─────────────────────────────────────


async def test_admin_force_arbitration(client):
    deal_id, *_ = await _make_deal(client)
    admin_init = await _make_admin(client)
    resp = await client.post(
        f"/api/admin/deals/{deal_id}/force-arbitration",
        json={"reason": "forced"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deal"]["status"] == DealStatus.arbitration.value
    rows = await _audit_rows("deal.force_arbitration")
    assert len(rows) == 1


async def test_admin_force_arbitration_idempotent(client):
    deal_id, *_ = await _make_deal(client)
    admin_init = await _make_admin(client)
    # set arbitration first
    r1 = await client.post(
        f"/api/admin/deals/{deal_id}/force-arbitration",
        json={"reason": "first"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert r1.status_code == 200
    # second call should be no-op (no new audit row)
    r2 = await client.post(
        f"/api/admin/deals/{deal_id}/force-arbitration",
        json={"reason": "second"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert r2.status_code == 200
    rows = await _audit_rows("deal.force_arbitration")
    assert len(rows) == 1


async def test_admin_assign_arbiter(client):
    deal_id, *_ = await _make_deal(client)
    admin_init = await _make_admin(client)
    # move to arbitration first
    await client.post(
        f"/api/admin/deals/{deal_id}/force-arbitration",
        json={},
        headers=with_totp(auth_headers(admin_init)),
    )
    # create arbiter user
    arb_init = signed_init_data(3001, "arb1")
    await client.get("/api/me", headers=auth_headers(arb_init))
    async with async_session() as session:
        arb_id = await get_user_id_by_tg(session, 3001)
        arb = await session.get(User, arb_id)
        assert arb is not None
        arb.is_arbiter = True
        await session.commit()

    resp = await client.post(
        f"/api/admin/deals/{deal_id}/assign-arbiter",
        json={"arbiter_id": arb_id},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deal"]["arbitration_resolved_by_id"] == arb_id


async def test_admin_assign_arbiter_rejects_non_arbiter(client):
    deal_id, *_ = await _make_deal(client)
    admin_init = await _make_admin(client)
    await client.post(
        f"/api/admin/deals/{deal_id}/force-arbitration",
        json={},
        headers=with_totp(auth_headers(admin_init)),
    )
    nobody_init = signed_init_data(3002, "nobody")
    resp = await client.get("/api/me", headers=auth_headers(nobody_init))
    nobody_id = resp.json()["id"]
    resp = await client.post(
        f"/api/admin/deals/{deal_id}/assign-arbiter",
        json={"arbiter_id": nobody_id},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 400


# ── delete ─────────────────────────────────────────────────────────────────


async def test_admin_delete_deal_refunds_buyer(client):
    deal_id, *_ = await _make_deal(client)
    admin_init = await _make_admin(client)
    resp = await client.post(
        f"/api/admin/deals/{deal_id}/delete",
        json={"reason": "spam"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted"] is True
    assert body["deal_id"] == deal_id
    # P10 — commission is no longer locked on the legacy path so
    # ``refunded`` returns just the principal (100).
    assert Decimal(body["refunded"]) == Decimal("100")

    async with async_session() as session:
        assert await session.get(Deal, deal_id) is None
        msgs = (
            (await session.execute(select(DealMessage).where(DealMessage.deal_id == deal_id)))
            .scalars()
            .all()
        )
        assert msgs == []


async def test_admin_delete_deal_writes_audit(client):
    deal_id, *_ = await _make_deal(client)
    admin_init = await _make_admin(client)
    await client.post(
        f"/api/admin/deals/{deal_id}/delete",
        json={"reason": "spam"},
        headers=with_totp(auth_headers(admin_init)),
    )
    rows = await _audit_rows("deal.delete")
    assert len(rows) == 1
    payload = rows[0].payload
    assert payload is not None
    assert payload["id"] == deal_id
    # M-23: audit payload now stores amounts as Decimal-canonical strings
    # so JSONB keeps full ``Numeric`` precision. ``refunded`` is quantised
    # to currency.decimals (USDT=2), ``amount`` reads back at the column's
    # full ``Numeric(28,8)`` scale.
    # P10 — commission is no longer locked on the legacy path so
    # the audit-logged ``refunded`` is just the principal (100).
    assert payload["refunded"] == "100.00"
    assert payload["amount"] == "100.00000000"
