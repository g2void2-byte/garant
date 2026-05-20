"""V5-B — wallet/withdrawals follow-ups regression suite.

One pricked test per fix in the V5-B audit bucket (``audit-status-v8.md
§2.C``):

* V5-B-3 — ``create_deposit_invoice`` rejects an upstream invoice with no
  pay_url for the wallet deposit path. (The legacy USD path was retired
  by H-1.)
* V5-B-4 — ``create_withdrawal`` rejects an address that doesn't match
  the per-currency regex stored on ``Currency.address_regex``.
* V5-B-8 — Crypto Pay webhook ignores payloads that only carry the
  legacy ``"type"`` field instead of ``"update_type"`` (the fallback
  was dropped).
* V5-B-9 — admin withdrawals counters use one ``GROUP BY`` query and
  report every status, including those not present in the table.
* V5-B-10 — ``GET /api/wallet/deposits/{id}`` is throttled to 2/30s
  per user.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import (
    Currency,
    User,
    UserBalance,
    WalletDeposit,
    WalletDepositStatus,
    WalletWithdrawal,
    WalletWithdrawStatus,
)
from tests.helpers import (
    auth_headers,
    credit_balance,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)

# ── V5-B-3 — pay_url must be non-empty ──────────────────────────────────


class _BlankUrlInvoice:
    """CryptoPay-shaped invoice with every URL slot empty.

    ``services_wallet.create_deposit_invoice`` runs the four-field
    fallback chain; if every field is falsy the function must reject
    with 502 instead of writing ``pay_url=""`` to the DB.
    """

    invoice_id = 1234567890
    status = "active"
    asset = "USDT"
    amount = "10"
    pay_url = ""
    bot_invoice_url = None
    mini_app_invoice_url = None
    web_app_invoice_url = None
    description = None
    payload = None
    paid_at = None
    created_at = None


class _BlankUrlCryptoPay:
    """Drop-in replacement for ``CryptoPay`` that returns a blank-URL invoice."""

    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def create_invoice(self, *, asset, amount, **_kwargs):  # noqa: ARG002
        return _BlankUrlInvoice()


@pytest.mark.asyncio
async def test_create_deposit_invoice_rejects_blank_pay_url(client, monkeypatch):
    """Wallet path — blank pay_url from CryptoBot must surface as 502."""
    from backend.app.config import settings

    init = signed_init_data(8001, "blank_url_user")
    await setup_pin(client, init)

    monkeypatch.setattr(settings, "cryptobot_token", "test-token-blank-url")
    import backend.app.services_wallet as services_wallet

    monkeypatch.setattr(services_wallet, "CryptoPay", _BlankUrlCryptoPay)

    resp = await client.post(
        "/api/wallet/deposits",
        json={"currency_code": "USDT", "amount": 10.0},
        headers=auth_headers(init),
    )
    assert resp.status_code == 502, resp.text


# ── V5-B-4 — per-currency address regex ─────────────────────────────────


@pytest.mark.asyncio
async def test_withdrawal_rejects_malformed_usdt_address(client):
    """Garbage in the ``address`` field for USDT (TRC20) must hit the
    regex check **before** we touch the balance row."""
    init = signed_init_data(8101, "addr_regex_user")
    pin_token = await setup_pin(client, init)

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 8101)
        await credit_balance(session, user_id, "USDT", 500.0)

    resp = await client.post(
        "/api/wallet/withdrawals",
        json={"currency_code": "USDT", "amount": 50.0, "address": "not-a-tron-address"},
        headers={**auth_headers(init), "X-Pin-Token": pin_token},
    )
    assert resp.status_code == 400, resp.text
    assert "USDT" in resp.json().get("detail", "")

    # Funds untouched: nothing moved to locked.
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        bal = (
            await session.execute(
                select(UserBalance).where(
                    UserBalance.user_id == user_id,
                    UserBalance.currency_id == usdt.id,
                )
            )
        ).scalar_one()
        assert float(bal.amount) == 500.0
        assert float(bal.locked) == 0.0


@pytest.mark.asyncio
async def test_withdrawal_accepts_wellformed_usdt_address(client):
    """A 34-char base58 ``T``-prefixed address must pass the regex check."""
    init = signed_init_data(8102, "addr_regex_ok")
    pin_token = await setup_pin(client, init)

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 8102)
        await credit_balance(session, user_id, "USDT", 500.0)

    resp = await client.post(
        "/api/wallet/withdrawals",
        json={"currency_code": "USDT", "amount": 50.0, "address": "T" + "x" * 33},
        headers={**auth_headers(init), "X-Pin-Token": pin_token},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_withdrawal_empty_regex_skips_check(client):
    """A currency with ``address_regex=""`` must bypass the format check
    (back-compat for newly-seeded assets with no regex yet)."""
    init = signed_init_data(8103, "addr_regex_skip")
    pin_token = await setup_pin(client, init)

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 8103)
        # Spin up an ad-hoc currency for this test so we don't have to
        # mutate one of the seeded rows (which would leak into sibling
        # tests). ``X8K`` is unused.
        cur = Currency(
            code="X8K",
            name="Skip-regex test currency",
            network="X8K",
            decimals=2,
            min_deposit=1,
            min_withdraw=1,
            sort_order=999,
            is_active=True,
            address_regex="",
        )
        session.add(cur)
        await session.commit()
        await session.refresh(cur)

        bal = UserBalance(user_id=user_id, currency_id=cur.id, amount=500, locked=0)
        session.add(bal)
        await session.commit()

    resp = await client.post(
        "/api/wallet/withdrawals",
        json={"currency_code": "X8K", "amount": 10.0, "address": "whatever-the-regex-is-empty"},
        headers={**auth_headers(init), "X-Pin-Token": pin_token},
    )
    assert resp.status_code == 200, resp.text


# ── shared helpers ──────────────────────────────────────────────────────


async def _bootstrap_user(client, *, tg: int, username: str) -> int:
    init = signed_init_data(tg, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _make_admin(client, *, tg: int) -> str:
    init = signed_init_data(tg, f"admin_{tg}")
    uid = await _bootstrap_user(client, tg=tg, username=f"admin_{tg}")
    async with async_session() as session:
        u = await session.get(User, uid)
        u.is_admin = True
        await session.commit()
    return init


# ── V5-B-8 — legacy ``type`` fallback removed ───────────────────────────


def _sign(body: bytes) -> str:
    """Mirror ``services_payments.verify_webhook_signature``."""
    secret = "test-cryptobot-token-for-pytest"
    key = hashlib.sha256(secret.encode()).digest()
    return hmac.new(key, body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_webhook_ignores_legacy_type_field(client):
    """A payload that only carries the legacy ``"type"`` envelope field
    must be ignored — the router has dropped the fallback, so even a
    well-signed ``type=invoice_paid`` envelope without
    ``update_type`` returns the catch-all ``{"ok": False}`` shape and
    does NOT credit the deposit."""
    init = signed_init_data(8301, "legacy_type")
    await setup_pin(client, init)

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 8301)
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        usdt_id = usdt.id
        session.add(
            WalletDeposit(
                user_id=user_id,
                currency_id=usdt_id,
                amount=Decimal("17.0"),
                provider_invoice_id="cb-legacy-type-1",
                pay_url="http://example.com/pay",
                status=WalletDepositStatus.pending,
            )
        )
        await session.commit()

    body = json.dumps(
        # Note: NO ``update_type`` field — only the legacy ``type``.
        {"type": "invoice_paid", "payload": {"invoice_id": "cb-legacy-type-1", "status": "paid"}}
    ).encode()
    resp = await client.post(
        "/api/payments/webhook/cryptobot",
        content=body,
        headers={
            "crypto-pay-api-signature": _sign(body),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200, resp.text
    # The router falls through to the catch-all branch with
    # ``{"ok": True, "ignored": "unknown"}``. The critical bit is
    # ``ignored=unknown`` — proves the legacy ``"type"`` field did NOT
    # drive routing into ``handle_invoice_paid``.
    payload_resp = resp.json()
    assert payload_resp.get("ignored") == "unknown", payload_resp
    assert "already_paid" not in payload_resp, payload_resp

    # Deposit stays ``pending`` — no double-credit slipped through.
    async with async_session() as session:
        dep = (
            await session.execute(
                select(WalletDeposit).where(WalletDeposit.provider_invoice_id == "cb-legacy-type-1")
            )
        ).scalar_one()
        assert dep.status == WalletDepositStatus.pending


# ── V5-B-9 — counters come from one GROUP BY query ──────────────────────


@pytest.mark.asyncio
async def test_admin_withdrawals_counters_cover_every_status(client):
    """Counters must return a key for every ``WalletWithdrawStatus`` —
    including statuses with zero rows in the table — so the frontend
    tab bar doesn't have to handle missing keys."""
    admin_init = await _make_admin(client, tg=8401)
    bob_id = await _bootstrap_user(client, tg=8402, username="counters_bob")

    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        session.add_all(
            [
                WalletWithdrawal(
                    user_id=bob_id,
                    currency_id=usdt.id,
                    amount=Decimal("1.0"),
                    address="T" + "y" * 33,
                    status=WalletWithdrawStatus.pending,
                ),
                WalletWithdrawal(
                    user_id=bob_id,
                    currency_id=usdt.id,
                    amount=Decimal("2.0"),
                    address="T" + "y" * 33,
                    status=WalletWithdrawStatus.pending,
                ),
                WalletWithdrawal(
                    user_id=bob_id,
                    currency_id=usdt.id,
                    amount=Decimal("3.0"),
                    address="T" + "y" * 33,
                    status=WalletWithdrawStatus.rejected,
                ),
            ]
        )
        await session.commit()

    resp = await client.get("/api/admin/withdrawals", headers=auth_headers(admin_init))
    assert resp.status_code == 200, resp.text
    counters = resp.json()["counters"]

    # Every enum value has a key (even if zero), and the seeded rows
    # show up in the right bucket.
    for status in ("pending", "approved", "sent", "rejected"):
        assert status in counters, counters
    assert counters["pending"] >= 2
    assert counters["rejected"] >= 1
    # No row was ever ``approved`` or ``sent`` for this fixture.
    assert counters["approved"] == 0
    assert counters["sent"] == 0


# ── V5-B-10 — wallet-poll throttle ──────────────────────────────────────


@pytest.mark.asyncio
async def test_deposit_polling_endpoint_is_throttled(client):
    """``GET /api/wallet/deposits/{id}`` must enforce 2/30s per user —
    the 3rd request within the window returns 429 instead of paying the
    upstream CryptoBot quota for a hot-loop client."""
    init = signed_init_data(8501, "poll_throttle")
    await setup_pin(client, init)

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 8501)
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        # Seed a ``paid`` deposit so ``poll_deposit_status`` short-circuits
        # without trying to reach CryptoBot — we want to exercise the
        # rate limit on the request, not the upstream call.
        dep = WalletDeposit(
            user_id=user_id,
            currency_id=usdt.id,
            amount=Decimal("5.0"),
            provider_invoice_id="cb-poll-throttle-1",
            pay_url="http://example.com/pay",
            status=WalletDepositStatus.paid,
        )
        session.add(dep)
        await session.commit()
        await session.refresh(dep)
        dep_id = dep.id

    # Drop in-memory buckets so this test isn't gated by a sibling's
    # leftover hits — the rate-limit module exposes a fixture-aware
    # reset for exactly this purpose.
    from backend.app.rate_limit import reset_state_for_tests

    reset_state_for_tests()

    r1 = await client.get(f"/api/wallet/deposits/{dep_id}", headers=auth_headers(init))
    r2 = await client.get(f"/api/wallet/deposits/{dep_id}", headers=auth_headers(init))
    r3 = await client.get(f"/api/wallet/deposits/{dep_id}", headers=auth_headers(init))

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r3.status_code == 429, r3.text
