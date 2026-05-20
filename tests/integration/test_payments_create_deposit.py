"""POST /api/wallet/deposits — provider routing.

The endpoint now takes an optional ``provider`` field:

* ``"cryptobot"`` (default for backwards compatibility) routes to the
  legacy CryptoPay flow,
* ``"crystalpay"`` routes to the v3 Crystalpay client and persists a
  ``WalletDeposit`` row with ``provider=crystalpay``,
* anything else is rejected by the pydantic ``Literal`` at the
  schema layer.

Both upstream clients are stubbed so the test never hits the network.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.helpers import auth_headers, setup_pin, signed_init_data


class _StubCryptoInvoice:
    invoice_id = 12345
    pay_url = "https://pay.crypt.bot/$cb-test"
    bot_invoice_url = "https://pay.crypt.bot/$cb-test"
    mini_app_invoice_url = ""
    web_app_invoice_url = ""


class _StubCryptoPay:
    """Drop-in replacement for ``services_wallet.CryptoPay``."""

    def __init__(self, *_a, **_kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def create_invoice(self, **_kwargs):
        return _StubCryptoInvoice()


class _StubCrystalInvoice:
    id = "cp-test-1"
    url = "https://pay.crystalpay.io/cp-test-1"
    state = "created"


class _StubCrystalpay:
    """Drop-in replacement for ``services_wallet.Crystalpay``."""

    def __init__(self, *_a, **_kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def create_invoice(self, **_kwargs):
        return _StubCrystalInvoice()


@pytest.mark.asyncio
async def test_create_deposit_default_routes_to_cryptobot(client, monkeypatch):
    """Omitting ``provider`` keeps the legacy CryptoBot path."""
    from backend.app import services_wallet
    from backend.app.db import async_session
    from backend.app.models import WalletDeposit, WalletDepositProvider

    init = signed_init_data(50001, "cb-default")
    await setup_pin(client, init)

    monkeypatch.setattr(services_wallet, "CryptoPay", _StubCryptoPay)

    resp = await client.post(
        "/api/wallet/deposits",
        json={"currency_code": "USDT", "amount": 10.0},
        headers=auth_headers(init),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "cryptobot"
    assert body["invoice_id"] == "12345"

    async with async_session() as session:
        dep = (
            await session.execute(
                select(WalletDeposit).where(WalletDeposit.provider_invoice_id == "12345")
            )
        ).scalar_one()
        assert dep.provider == WalletDepositProvider.cryptobot


@pytest.mark.asyncio
async def test_create_deposit_crystalpay_routes_to_v3_client(client, monkeypatch):
    """``provider="crystalpay"`` issues a Crystalpay v3 invoice."""
    from backend.app import services_wallet
    from backend.app.db import async_session
    from backend.app.models import WalletDeposit, WalletDepositProvider

    init = signed_init_data(50002, "cp-route")
    await setup_pin(client, init)

    monkeypatch.setattr(services_wallet, "Crystalpay", _StubCrystalpay)

    resp = await client.post(
        "/api/wallet/deposits",
        json={
            "currency_code": "USDT",
            "amount": 12.0,
            "provider": "crystalpay",
        },
        headers=auth_headers(init),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "crystalpay"
    assert body["invoice_id"] == "cp-test-1"
    assert body["pay_url"] == "https://pay.crystalpay.io/cp-test-1"

    async with async_session() as session:
        dep = (
            await session.execute(
                select(WalletDeposit).where(WalletDeposit.provider_invoice_id == "cp-test-1")
            )
        ).scalar_one()
        assert dep.provider == WalletDepositProvider.crystalpay


@pytest.mark.asyncio
async def test_create_deposit_explicit_cryptobot_provider(client, monkeypatch):
    """Explicit ``provider="cryptobot"`` still works."""
    from backend.app import services_wallet

    init = signed_init_data(50003, "cb-explicit")
    await setup_pin(client, init)

    monkeypatch.setattr(services_wallet, "CryptoPay", _StubCryptoPay)

    resp = await client.post(
        "/api/wallet/deposits",
        json={
            "currency_code": "USDT",
            "amount": 5.0,
            "provider": "cryptobot",
        },
        headers=auth_headers(init),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "cryptobot"


@pytest.mark.asyncio
async def test_create_deposit_unknown_provider_returns_422(client):
    """Pydantic ``Literal`` validates the provider field at the edge."""
    init = signed_init_data(50004, "bad-provider")
    await setup_pin(client, init)

    resp = await client.post(
        "/api/wallet/deposits",
        json={
            "currency_code": "USDT",
            "amount": 5.0,
            "provider": "stripe",
        },
        headers=auth_headers(init),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_create_deposit_crystalpay_unconfigured_returns_502(client, monkeypatch):
    """Empty Crystalpay credentials must surface as 502, not crash."""
    from backend.app.config import settings

    init = signed_init_data(50005, "cp-noconfig")
    await setup_pin(client, init)

    monkeypatch.setattr(settings, "crystalpay_login", "")
    monkeypatch.setattr(settings, "crystalpay_secret", "")

    resp = await client.post(
        "/api/wallet/deposits",
        json={
            "currency_code": "USDT",
            "amount": 5.0,
            "provider": "crystalpay",
        },
        headers=auth_headers(init),
    )
    assert resp.status_code == 502, resp.text
