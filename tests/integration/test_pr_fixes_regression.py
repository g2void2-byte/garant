"""Regression tests for all fixes in the current PR.

Covers:
1. Public reviews creation persistence (commit to DB).
2. Resolve endpoint returns 403 Forbidden for unauthorized non-admins/non-arbiters.
3. Case-insensitive signature verification in Crystalpay webhook.
4. Admin delete deal cleans up orphan attached media without deleting shared media.
5. Late topup payment webhook credits buyer's spendable balance instead of resurrecting the deal.
"""

from __future__ import annotations

import hashlib
import io
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select

import backend.app.services_wallet as services_wallet
from backend.app.config import settings
from backend.app.db import async_session
from backend.app.models import (
    Currency,
    Deal,
    DealStatus,
    Media,
    Review,
    User,
    UserBalance,
    WalletDeposit,
    WalletDepositProvider,
    WalletDepositStatus,
)
from backend.app.services_deals import complete_deal_topup_payment
from tests.helpers import (
    auth_headers,
    credit_balance,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
    tiny_image_bytes,
    with_totp,
)


async def test_create_review_commits_to_db(client):
    init_author = signed_init_data(6001, "buyer_r")
    init_target = signed_init_data(6002, "seller_r")
    await setup_pin(client, init_author)
    await setup_pin(client, init_target)

    async with async_session() as session:
        author_id = await get_user_id_by_tg(session, 6001)
        target_id = await get_user_id_by_tg(session, 6002)
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        deal = Deal(
            buyer_id=author_id,
            seller_id=target_id,
            amount=10,
            currency_id=usdt.id,
            status=DealStatus.completed,
        )
        session.add(deal)
        await session.commit()
        deal_id = deal.id

    resp = await client.post(
        "/api/reviews",
        json={
            "deal_id": deal_id,
            "target_username": "seller_r",
            "rating": 5,
            "text": "Отличная сделка!",
        },
        headers=auth_headers(init_author),
    )
    assert resp.status_code == 201, resp.text

    # Now verify it's persisted in the DB
    async with async_session() as session:
        reviews = (
            await session.execute(
                select(Review).where(Review.deal_id == deal_id, Review.author_id == author_id)
            )
        ).scalars().all()
        assert len(reviews) == 1
        assert reviews[0].text == "Отличная сделка!"


async def test_resolve_arbitration_non_admin_returns_403(client):
    init_buyer = signed_init_data(6011, "buyer_resolve")
    init_seller = signed_init_data(6012, "seller_resolve")
    await setup_pin(client, init_buyer)
    await setup_pin(client, init_seller)

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 6011)
        seller_id = await get_user_id_by_tg(session, 6012)
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        deal = Deal(
            buyer_id=buyer_id,
            seller_id=seller_id,
            amount=10,
            currency_id=usdt.id,
            status=DealStatus.arbitration,
        )
        session.add(deal)
        await session.commit()
        deal_id = deal.id

    # Resolve arbitration as buyer (not admin or arbiter)
    resp = await client.post(
        f"/api/deals/{deal_id}/resolve",
        json={"winner": "buyer", "note": "Resolved by buyer"},
        headers=auth_headers(init_buyer),
    )
    assert resp.status_code == 403
    assert "Доступ запрещён" in resp.text


async def test_resolve_arbitration_admin_requires_totp(client):
    init_buyer = signed_init_data(6013, "buyer_resolve_totp")
    init_seller = signed_init_data(6014, "seller_resolve_totp")
    init_admin = signed_init_data(6015, "admin_resolve_totp")
    await setup_pin(client, init_buyer)
    await setup_pin(client, init_seller)
    me = await client.get("/api/me", headers=auth_headers(init_admin))
    assert me.status_code == 200, me.text

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 6013)
        seller_id = await get_user_id_by_tg(session, 6014)
        admin = (
            await session.execute(select(User).where(User.tg_user_id == 6015))
        ).scalar_one()
        admin.is_admin = True
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        deal = Deal(
            buyer_id=buyer_id,
            seller_id=seller_id,
            amount=10,
            currency_id=usdt.id,
            status=DealStatus.arbitration,
        )
        session.add(deal)
        await session.commit()
        deal_id = deal.id

    resp = await client.post(
        f"/api/deals/{deal_id}/resolve",
        json={"winner": "buyer", "note": "missing 2FA"},
        headers=auth_headers(init_admin),
    )
    assert resp.status_code in (401, 403)

    resp = await client.post(
        f"/api/deals/{deal_id}/resolve",
        json={"winner": "buyer", "note": "with 2FA"},
        headers=with_totp(auth_headers(init_admin)),
    )
    assert resp.status_code == 200, resp.text


async def test_crystalpay_webhook_signature_case_insensitive(client):
    init_data = signed_init_data(6021, "alice-cp-case")
    await setup_pin(client, init_data)

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 6021)
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        session.add(
            WalletDeposit(
                user_id=user_id,
                currency_id=usdt.id,
                amount=7.5,
                provider=WalletDepositProvider.crystalpay,
                provider_invoice_id="cp-case-100",
                pay_url="https://pay.crystalpay.io/cp-case-100",
                status=WalletDepositStatus.pending,
            )
        )
        await session.commit()

    # Generate an UPPERCASE signature
    sig = hashlib.sha1(f"cp-case-100:{settings.crystalpay_secret}".encode()).hexdigest().upper()

    body = {
        "id": "cp-case-100",
        "state": "payed",
        "amount": "7.5",
        "currency": "USDT",
        "signature": sig,
    }
    resp = await client.post("/api/payments/webhook/crystalpay", json=body)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["ok"] is True
    assert payload.get("kind") == "wallet"


async def test_admin_delete_deal_cleans_media_files(client):
    # 1. Create a deal
    buyer_init = signed_init_data(6031, "buyer_del_media")
    seller_init = signed_init_data(6032, "seller_del_media")
    buyer_pin = await setup_pin(client, buyer_init)
    await setup_pin(client, seller_init)

    # Fund buyer's balance so deal creation doesn't fail with insufficient_funds
    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 6031)
        await credit_balance(session, buyer_id, "USDT", 200.0)

    create = await client.post(
        "/api/deals",
        json={
            "counterparty": "seller_del_media",
            "role": "buyer",
            "amount": 100,
            "description": "for media deletion testing",
            "currency_code": "USDT",
        },
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    assert create.status_code == 201, create.text
    deal_id = create.json()["id"]

    # 2. Upload a file
    png_bytes = tiny_image_bytes("PNG")
    files = {"file": ("a.png", io.BytesIO(png_bytes), "image/png")}
    up = await client.post(
        "/api/media/upload",
        data={"kind": "deal"},
        files=files,
        headers=auth_headers(buyer_init),
    )
    assert up.status_code == 201, up.text
    media_id = up.json()["id"]

    # 3. Send message referencing upload
    resp = await client.post(
        f"/api/deals/{deal_id}/messages",
        json={"text": "check out this", "attachments": [media_id]},
        headers=auth_headers(buyer_init),
    )
    assert resp.status_code == 201, resp.text

    # Get media path to verify file existence
    async with async_session() as session:
        m = await session.get(Media, media_id)
        assert m is not None
        filename = m.url.split("/")[-1]
        media_root = Path(settings.media_root).expanduser().resolve()
        file_path = media_root / m.kind / filename
        assert file_path.exists()

    # 4. Make an admin and delete the deal
    admin_init = signed_init_data(9099, "admin_del_media")
    await client.get("/api/me", headers=auth_headers(admin_init))
    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 9099)
        user = await session.get(User, user_id)
        user.is_admin = True
        await session.commit()

    del_resp = await client.post(
        f"/api/admin/deals/{deal_id}/delete",
        json={"reason": "cleanup test"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert del_resp.status_code == 200, del_resp.text

    # 5. Verify Media row and file are deleted
    async with async_session() as session:
        assert await session.get(Media, media_id) is None
        assert await session.get(Deal, deal_id) is None
        assert not file_path.exists()


async def test_admin_delete_deal_keeps_media_referenced_by_other_deals(client):
    buyer_init = signed_init_data(6033, "buyer_shared_media")
    seller_one_init = signed_init_data(6034, "seller_shared_one")
    seller_two_init = signed_init_data(6035, "seller_shared_two")
    buyer_pin = await setup_pin(client, buyer_init)
    await setup_pin(client, seller_one_init)
    await setup_pin(client, seller_two_init)

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 6033)
        await credit_balance(session, buyer_id, "USDT", 200.0)

    async def create_deal(counterparty: str, description: str) -> int:
        resp = await client.post(
            "/api/deals",
            json={
                "counterparty": counterparty,
                "role": "buyer",
                "amount": 50,
                "description": description,
                "currency_code": "USDT",
            },
            headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    deal_one_id = await create_deal("seller_shared_one", "first shared media deal")
    deal_two_id = await create_deal("seller_shared_two", "second shared media deal")

    png_bytes = tiny_image_bytes("PNG")
    files = {"file": ("shared.png", io.BytesIO(png_bytes), "image/png")}
    up = await client.post(
        "/api/media/upload",
        data={"kind": "deal"},
        files=files,
        headers=auth_headers(buyer_init),
    )
    assert up.status_code == 201, up.text
    media_id = up.json()["id"]

    for deal_id in (deal_one_id, deal_two_id):
        resp = await client.post(
            f"/api/deals/{deal_id}/messages",
            json={"text": "same proof", "attachments": [media_id]},
            headers=auth_headers(buyer_init),
        )
        assert resp.status_code == 201, resp.text

    async with async_session() as session:
        m = await session.get(Media, media_id)
        assert m is not None
        filename = m.url.split("/")[-1]
        media_root = Path(settings.media_root).expanduser().resolve()
        file_path = media_root / m.kind / filename
        assert file_path.exists()

    admin_init = signed_init_data(9100, "admin_shared_media")
    await client.get("/api/me", headers=auth_headers(admin_init))
    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 9100)
        user = await session.get(User, user_id)
        user.is_admin = True
        await session.commit()

    del_resp = await client.post(
        f"/api/admin/deals/{deal_one_id}/delete",
        json={"reason": "cleanup shared media test"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert del_resp.status_code == 200, del_resp.text

    async with async_session() as session:
        assert await session.get(Media, media_id) is not None
        assert await session.get(Deal, deal_one_id) is None
        assert await session.get(Deal, deal_two_id) is not None
        assert file_path.exists()

    listed = await client.get(
        f"/api/deals/{deal_two_id}/messages",
        headers=auth_headers(seller_two_init),
    )
    assert listed.status_code == 200, listed.text
    messages = listed.json()
    assert messages[0]["attachments"][0]["id"] == media_id


async def test_late_payment_credits_buyer_balance_instead_of_deal_resurrection(client):
    buyer_init = signed_init_data(6041, "buyer_late")
    seller_init = signed_init_data(6042, "seller_late")
    buyer_pin = await setup_pin(client, buyer_init)
    await setup_pin(client, seller_init)

    # Stub CryptoPay so create_deal_with_topup doesn't hit real API
    _counter = [0]

    async def _fake_create_invoice(**_kwargs):
        _counter[0] += 1
        inv = MagicMock()
        inv.invoice_id = _counter[0]
        inv.pay_url = f"https://pay.crypt.bot/$cb-{_counter[0]}"
        inv.bot_invoice_url = inv.pay_url
        inv.mini_app_invoice_url = ""
        inv.web_app_invoice_url = ""
        return inv

    fake_cp = MagicMock()
    fake_cp.__aenter__ = AsyncMock(return_value=fake_cp)
    fake_cp.__aexit__ = AsyncMock(return_value=None)
    fake_cp.create_invoice = _fake_create_invoice

    fake_cp_class = MagicMock(return_value=fake_cp)

    with patch.object(services_wallet, "CryptoPay", fake_cp_class), \
         patch.object(services_wallet, "is_cryptopay_configured", return_value=True):

        # 1. Create a deal with topup
        resp = await client.post(
            "/api/deals/with-topup",
            json={
                "counterparty": "seller_late",
                "role": "buyer",
                "amount": 100,
                "description": "late payment test",
                "currency_code": "USDT",
            },
            headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        deal_id = body["deal"]["id"]
        deposit_id = body["deal"]["topup_deposit_id"]

    # 2. Simulate that the deal is completed (or cancelled)
    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        deal.status = DealStatus.completed
        await session.commit()

    # 3. Webhook fires for the deposit (late payment)
    async with async_session() as session:
        deposit = (
            await session.execute(
                select(WalletDeposit)
                .where(WalletDeposit.id == deposit_id)
                .with_for_update()
            )
        ).scalar_one()
        await complete_deal_topup_payment(session, deposit, paid_amount=Decimal("105"))
        await session.commit()

    # 4. Verify deal was not resurrected and buyer's balance is credited
    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        assert deal.status == DealStatus.completed  # Still completed!

        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        buyer_id = await get_user_id_by_tg(session, 6041)
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == buyer_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        # Spendable balance should be credited with the paid amount (105)
        assert float(bal.amount) == 105.0
        # No locked balance from this payment
        assert float(bal.locked) == 0.0
