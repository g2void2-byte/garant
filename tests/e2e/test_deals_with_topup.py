"""P10 — commission-via-invoice deal flow end-to-end coverage.

The legacy ``POST /api/deals`` path (balance-only, no commission
locked) is exercised by ``test_deals_happy.py``. This module covers
the new ``POST /api/deals/with-topup`` happy path plus every
webhook-driven branch in ``complete_deal_topup_payment``:

* §1  Happy path — buyer with zero balance, webhook lands exact
       ``invoice_total`` (``topup_principal + commission``); deal
       advances to ``pending_confirmation``, ``UserBalance.locked``
       equals the principal, ``commission_paid`` flips to ``True``.

* §2  Commission-only — buyer's balance already covers ``amount``,
       so the invoice charges just the commission. Same happy-path
       transition, ``UserBalance.amount`` keeps the pre-deal value
       minus the principal (which moves to ``locked``).

* §3  Underpayment (paid < commission) — all paid lands on
       spendable balance, deal stays ``pending_topup``,
       ``commission_paid`` stays ``False``.

* §4  Underpayment (paid >= commission but post-credit balance <
       principal) — commission deducted, the rest credited, deal
       stays ``pending_topup``.

* §5  Overpayment — paid > ``invoice_total``; the excess lands on
       spendable balance after the principal is locked. Deal
       advances normally.

* §6  Idempotent webhook — two deliveries of the same paid amount
       only credit the buyer once and don't reset the deal state.

* §7  ``sweep_pending_topup`` flips stale ``pending_topup`` deals
       to ``cancelled_for_inactivity`` and expires the linked
       deposit. Nothing is refunded — the principal was never
       locked.

* §8  Buyer-side cancel — ``POST /api/deals/{id}/cancel-topup``
       lets the buyer abort a ``pending_topup`` deal before paying.
       Same deposit-expiry side effect; deal lands in
       ``cancelled``.

The CryptoPay client is stubbed end-to-end so no test reaches the
real CryptoBot API.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from tests.helpers import (
    auth_headers,
    credit_balance,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)


async def _create_with_topup(
    client,
    buyer_init,
    buyer_pin,
    *,
    counterparty: str,
    amount: float = 100.0,
    currency_code: str = "USDT",
):
    return await client.post(
        "/api/deals/with-topup",
        json={
            "counterparty": counterparty,
            "role": "buyer",
            "amount": amount,
            "description": "with-topup happy",
            "currency_code": currency_code,
        },
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )


async def _setup_pair(client, buyer_tg: int, seller_tg: int):
    buyer_init = signed_init_data(buyer_tg, f"buyer{buyer_tg}")
    seller_init = signed_init_data(seller_tg, f"seller{seller_tg}")
    buyer_pin = await setup_pin(client, buyer_init)
    await setup_pin(client, seller_init)
    return buyer_init, seller_init, buyer_pin


async def _settle_deposit(deal_id: int, *, paid_amount: Decimal | None = None):
    """Run ``complete_deal_topup_payment`` directly against the deal's
    linked deposit.

    Mirrors what the production CryptoBot webhook would do once it
    lands ``status='paid'`` for the underlying invoice.
    """
    from backend.app.db import async_session
    from backend.app.models import Deal, WalletDeposit
    from backend.app.services_deals import complete_deal_topup_payment

    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        assert deal is not None and deal.topup_deposit_id is not None
        deposit = (
            await session.execute(
                select(WalletDeposit)
                .where(WalletDeposit.id == deal.topup_deposit_id)
                .with_for_update()
            )
        ).scalar_one()
        await complete_deal_topup_payment(session, deposit, paid_amount=paid_amount)
        return deposit.id


# ── §1 Happy path ────────────────────────────────────────────────


async def test_with_topup_happy_path(client, _stub_cryptopay):
    from backend.app.db import async_session
    from backend.app.models import Currency, Deal, DealStatus, UserBalance

    buyer_init, _seller_init, buyer_pin = await _setup_pair(client, 30001, 30002)

    resp = await _create_with_topup(
        client, buyer_init, buyer_pin, counterparty="seller30002", amount=100.0
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    deal_id = body["deal"]["id"]
    assert body["deal"]["status"] == DealStatus.pending_topup.value
    assert body["deal"]["commission_paid"] is False
    invoice = body["invoice"]
    # commission default = 5% of 100 = 5; buyer has 0 balance so
    # topup_principal = 100 and total = 105.
    assert Decimal(invoice["topup_principal"]) == Decimal("100")
    assert Decimal(invoice["commission"]) == Decimal("5")
    assert Decimal(invoice["total"]) == Decimal("105")
    assert invoice["pay_url"].startswith("https://pay.crypt.bot/")

    # Inline copy on the deal too — the frontend reload path uses
    # this to resume the pay flow without a separate GET round-trip.
    inline = body["deal"]["topup_invoice"]
    assert inline is not None
    assert Decimal(inline["total"]) == Decimal("105")

    # Settle the deposit. The webhook posts the full ``invoice_total``.
    await _settle_deposit(deal_id, paid_amount=Decimal("105"))

    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        assert deal is not None
        assert deal.status == DealStatus.pending_confirmation
        assert deal.commission_paid is True

        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        buyer_id = await get_user_id_by_tg(session, 30001)
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == buyer_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        # Principal locked, spendable goes to zero (commission was
        # collected upstream — never reached the buyer's spendable
        # bucket).
        assert Decimal(str(bal.amount)) == Decimal("0")
        assert Decimal(str(bal.locked)) == Decimal("100")


# ── §2 Commission-only invoice ──────────────────────────────────


async def test_with_topup_commission_only(client, _stub_cryptopay):
    from backend.app.db import async_session
    from backend.app.models import Currency, Deal, DealStatus, UserBalance

    buyer_init, _seller_init, buyer_pin = await _setup_pair(client, 30101, 30102)

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 30101)
        # Buyer already has enough principal in spendable.
        await credit_balance(session, buyer_id, "USDT", 100)

    resp = await _create_with_topup(
        client, buyer_init, buyer_pin, counterparty="seller30102", amount=100.0
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    deal_id = body["deal"]["id"]
    invoice = body["invoice"]
    # Balance covers principal so topup_principal = 0; invoice is
    # just the commission (5).
    assert Decimal(invoice["topup_principal"]) == Decimal("0")
    assert Decimal(invoice["commission"]) == Decimal("5")
    assert Decimal(invoice["total"]) == Decimal("5")

    await _settle_deposit(deal_id, paid_amount=Decimal("5"))

    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        assert deal is not None
        assert deal.status == DealStatus.pending_confirmation
        assert deal.commission_paid is True
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        buyer_id = await get_user_id_by_tg(session, 30101)
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == buyer_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        # Started with 100 spendable; principal of 100 moves to locked.
        assert Decimal(str(bal.amount)) == Decimal("0")
        assert Decimal(str(bal.locked)) == Decimal("100")


# ── §3 Underpayment (paid < commission) ─────────────────────────


async def test_with_topup_underpayment_below_commission(client, _stub_cryptopay):
    from backend.app.db import async_session
    from backend.app.models import (
        Currency,
        Deal,
        DealStatus,
        UserBalance,
        WalletDeposit,
        WalletDepositStatus,
    )

    buyer_init, _seller_init, buyer_pin = await _setup_pair(client, 30201, 30202)

    resp = await _create_with_topup(
        client, buyer_init, buyer_pin, counterparty="seller30202", amount=100.0
    )
    assert resp.status_code == 201
    deal_id = resp.json()["deal"]["id"]

    # Pay less than the 5 commission.
    old_deposit_id = await _settle_deposit(deal_id, paid_amount=Decimal("2"))

    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        assert deal is not None
        assert deal.status == DealStatus.pending_topup  # unchanged
        assert deal.commission_paid is False
        assert deal.topup_deposit_id is not None
        assert deal.topup_deposit_id != old_deposit_id
        old_deposit = await session.get(WalletDeposit, old_deposit_id)
        replacement = await session.get(WalletDeposit, deal.topup_deposit_id)
        assert old_deposit is not None and old_deposit.status == WalletDepositStatus.paid
        assert replacement is not None and replacement.status == WalletDepositStatus.pending
        assert Decimal(str(replacement.amount)) == Decimal("103.00000000")
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        buyer_id = await get_user_id_by_tg(session, 30201)
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == buyer_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        # All paid (2) parked on spendable; nothing locked.
        assert Decimal(str(bal.amount)) == Decimal("2")
        assert Decimal(str(bal.locked)) == Decimal("0")


# ── §4 Underpayment (paid >= commission but balance < principal) ─


async def test_with_topup_underpayment_above_commission(client, _stub_cryptopay):
    from backend.app.db import async_session
    from backend.app.models import (
        Currency,
        Deal,
        DealStatus,
        UserBalance,
        WalletDeposit,
        WalletDepositStatus,
    )

    buyer_init, _seller_init, buyer_pin = await _setup_pair(client, 30301, 30302)

    resp = await _create_with_topup(
        client, buyer_init, buyer_pin, counterparty="seller30302", amount=100.0
    )
    assert resp.status_code == 201
    deal_id = resp.json()["deal"]["id"]

    # Pay commission (5) plus half the principal (50). Balance ends
    # at 50 which is still < 100, so the deal stays pending_topup.
    old_deposit_id = await _settle_deposit(deal_id, paid_amount=Decimal("55"))

    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        assert deal is not None
        assert deal.status == DealStatus.pending_topup
        assert deal.commission_paid is True
        assert deal.topup_deposit_id is not None
        assert deal.topup_deposit_id != old_deposit_id
        old_deposit = await session.get(WalletDeposit, old_deposit_id)
        replacement = await session.get(WalletDeposit, deal.topup_deposit_id)
        assert old_deposit is not None and old_deposit.status == WalletDepositStatus.paid
        assert replacement is not None and replacement.status == WalletDepositStatus.pending
        assert Decimal(str(replacement.amount)) == Decimal("50.00000000")
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        buyer_id = await get_user_id_by_tg(session, 30301)
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == buyer_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        # 55 paid - 5 commission = 50 credited to spendable.
        assert Decimal(str(bal.amount)) == Decimal("50")
        assert Decimal(str(bal.locked)) == Decimal("0")

    await _settle_deposit(deal_id, paid_amount=Decimal("50"))

    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        assert deal is not None
        assert deal.status == DealStatus.pending_confirmation
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        buyer_id = await get_user_id_by_tg(session, 30301)
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == buyer_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        assert Decimal(str(bal.amount)) == Decimal("0E-8")
        assert Decimal(str(bal.locked)) == Decimal("100.00000000")


# ── §5 Overpayment ──────────────────────────────────────────────


async def test_with_topup_overpayment_lands_excess_on_spendable(client, _stub_cryptopay):
    from backend.app.db import async_session
    from backend.app.models import Currency, Deal, DealStatus, UserBalance

    buyer_init, _seller_init, buyer_pin = await _setup_pair(client, 30401, 30402)

    resp = await _create_with_topup(
        client, buyer_init, buyer_pin, counterparty="seller30402", amount=100.0
    )
    assert resp.status_code == 201
    deal_id = resp.json()["deal"]["id"]

    # Overpay by 20 (total = 105, pays 125).
    await _settle_deposit(deal_id, paid_amount=Decimal("125"))

    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        assert deal is not None
        assert deal.status == DealStatus.pending_confirmation
        assert deal.commission_paid is True
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        buyer_id = await get_user_id_by_tg(session, 30401)
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == buyer_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        # paid = 125, commission = 5 → principal_credit = 120; lock
        # 100 of it, leave 20 on spendable.
        assert Decimal(str(bal.amount)) == Decimal("20")
        assert Decimal(str(bal.locked)) == Decimal("100")


# ── §6 Idempotent webhook delivery ──────────────────────────────


async def test_with_topup_webhook_idempotent(client, _stub_cryptopay):
    from backend.app.db import async_session
    from backend.app.models import Currency, UserBalance

    buyer_init, _seller_init, buyer_pin = await _setup_pair(client, 30501, 30502)

    resp = await _create_with_topup(
        client, buyer_init, buyer_pin, counterparty="seller30502", amount=100.0
    )
    assert resp.status_code == 201
    deal_id = resp.json()["deal"]["id"]

    await _settle_deposit(deal_id, paid_amount=Decimal("105"))
    # Second delivery — should be a no-op once the deposit is paid.
    await _settle_deposit(deal_id, paid_amount=Decimal("105"))

    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        buyer_id = await get_user_id_by_tg(session, 30501)
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == buyer_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        # Idempotent — no double credit, no double lock.
        assert Decimal(str(bal.amount)) == Decimal("0")
        assert Decimal(str(bal.locked)) == Decimal("100")


# ── §7 sweep_pending_topup ──────────────────────────────────────


async def test_sweep_pending_topup_cancels_stale_deals(client, _stub_cryptopay):
    from backend.app.db import async_session
    from backend.app.models import (
        AppSettings,
        Deal,
        DealStatus,
        WalletDeposit,
        WalletDepositStatus,
    )
    from backend.app.services_deals import sweep_pending_topup
    from backend.app.time_utils import utcnow

    buyer_init, _seller_init, buyer_pin = await _setup_pair(client, 30601, 30602)

    resp = await _create_with_topup(
        client, buyer_init, buyer_pin, counterparty="seller30602", amount=100.0
    )
    assert resp.status_code == 201
    deal_id = resp.json()["deal"]["id"]

    # Backdate the deal so the sweep picks it up.
    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        assert deal is not None
        settings_row = (await session.execute(select(AppSettings))).scalar_one()
        deal.created_at = utcnow() - timedelta(
            hours=int(settings_row.pending_topup_expiry_hours or 24) + 1
        )
        await session.commit()

        affected = await sweep_pending_topup(session)
        assert affected == 1

    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        assert deal is not None
        assert deal.status == DealStatus.cancelled_for_inactivity
        deposit = (
            await session.execute(
                select(WalletDeposit).where(WalletDeposit.id == deal.topup_deposit_id)
            )
        ).scalar_one()
        assert deposit.status == WalletDepositStatus.expired


# ── §8 Buyer-side cancel ────────────────────────────────────────


async def test_cancel_pending_topup_endpoint(client, _stub_cryptopay):
    from backend.app.db import async_session
    from backend.app.models import Deal, DealStatus, WalletDeposit, WalletDepositStatus

    buyer_init, _seller_init, buyer_pin = await _setup_pair(client, 30701, 30702)

    resp = await _create_with_topup(
        client, buyer_init, buyer_pin, counterparty="seller30702", amount=100.0
    )
    assert resp.status_code == 201
    deal_id = resp.json()["deal"]["id"]

    cancel = await client.post(
        f"/api/deals/{deal_id}/cancel-topup",
        headers={**auth_headers(buyer_init), "X-Pin-Token": buyer_pin},
    )
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == DealStatus.cancelled.value

    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        assert deal is not None
        assert deal.status == DealStatus.cancelled
        deposit = (
            await session.execute(
                select(WalletDeposit).where(WalletDeposit.id == deal.topup_deposit_id)
            )
        ).scalar_one()
        assert deposit.status == WalletDepositStatus.expired


async def test_cancel_pending_topup_rejects_seller(client, _stub_cryptopay):
    # ``_setup_pair`` already calls ``setup_pin`` for both sides; capture
    # the seller's pin token directly.
    buyer_init = signed_init_data(30801, "buyer30801")
    seller_init = signed_init_data(30802, "seller30802")
    buyer_pin = await setup_pin(client, buyer_init)
    seller_pin = await setup_pin(client, seller_init)

    resp = await _create_with_topup(
        client, buyer_init, buyer_pin, counterparty="seller30802", amount=100.0
    )
    assert resp.status_code == 201
    deal_id = resp.json()["deal"]["id"]

    cancel = await client.post(
        f"/api/deals/{deal_id}/cancel-topup",
        headers={**auth_headers(seller_init), "X-Pin-Token": seller_pin},
    )
    # Seller can't cancel the buyer's pending_topup deal.
    assert cancel.status_code == 400


# ── §9 P11-D1: balance-fully-covers (no invoice) ────────────────


async def test_with_topup_balance_fully_covers_skips_invoice(client, _stub_cryptopay):
    """P11-D1 — buyer's balance ≥ amount + commission → no invoice.

    Asserts the new short-circuit branch: the deal is created in
    ``pending_confirmation`` straight away, ``commission_paid``
    flips to ``True``, the principal is locked, the commission is
    debited off ``UserBalance.amount``, and the response carries
    ``invoice = None``.
    """
    from backend.app.db import async_session
    from backend.app.models import Currency, Deal, DealStatus, UserBalance

    buyer_init, _seller_init, buyer_pin = await _setup_pair(client, 30901, 30902)

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 30901)
        # 100 principal + 5 commission = 105 needed; give a little extra
        # so the deduction is visible in the post-call assertion.
        await credit_balance(session, buyer_id, "USDT", 200)

    resp = await _create_with_topup(
        client, buyer_init, buyer_pin, counterparty="seller30902", amount=100.0
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    deal_id = body["deal"]["id"]
    # Short-circuit: deal lands in pending_confirmation, commission
    # paid, no invoice attached.
    assert body["deal"]["status"] == DealStatus.pending_confirmation.value
    assert body["deal"]["commission_paid"] is True
    assert body["deal"]["topup_deposit_id"] is None
    assert body["invoice"] is None
    assert body["deal"]["topup_invoice"] is None

    async with async_session() as session:
        deal = await session.get(Deal, deal_id)
        assert deal is not None
        assert deal.status == DealStatus.pending_confirmation
        assert deal.commission_paid is True
        assert deal.topup_deposit_id is None

        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        buyer_id = await get_user_id_by_tg(session, 30901)
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == buyer_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        # Started with 200; needed 105 (100 principal + 5 commission).
        # 100 moves to locked, 5 burns off (platform's commission
        # share — same accounting as the upstream-invoice path).
        # Spendable should be 200 - 105 = 95.
        assert Decimal(str(bal.amount)) == Decimal("95")
        assert Decimal(str(bal.locked)) == Decimal("100")


# ── §10 P11-D1: tiny commission below min_deposit ───────────────


async def test_with_topup_commission_below_min_deposit_uses_skip_min(client, _stub_cryptopay):
    """P11-D1 — commission-only invoice smaller than ``currency.min_deposit``.

    Buyer's balance covers the principal but not the commission. The
    invoice charges only the commission, which is below the USD
    ``min_deposit`` of 1.0. The old code bounced this with HTTP 400
    ("Минимальная сумма пополнения"); the new ``min_check=False``
    escape hatch lets the deal-create path bypass that check.
    """
    from backend.app.db import async_session
    from backend.app.models import DealStatus

    buyer_init, _seller_init, buyer_pin = await _setup_pair(client, 31001, 31002)

    async with async_session() as session:
        buyer_id = await get_user_id_by_tg(session, 31001)
        # 10 principal + 0.5 commission = 10.5 needed; give 10 so the
        # buyer has the principal but not the commission.
        await credit_balance(session, buyer_id, "USD", 10)

    resp = await _create_with_topup(
        client,
        buyer_init,
        buyer_pin,
        counterparty="seller31002",
        amount=10.0,
        currency_code="USD",
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    invoice = body["invoice"]
    assert invoice is not None
    # invoice_total = 0 principal + 0.5 commission = 0.5 USD (below
    # min_deposit=1.0 USD). The min_check=False escape hatch lets
    # this through.
    assert Decimal(invoice["topup_principal"]) == Decimal("0")
    assert Decimal(invoice["commission"]) == Decimal("0.5")
    assert Decimal(invoice["total"]) == Decimal("0.5")
    assert body["deal"]["status"] == DealStatus.pending_topup.value
