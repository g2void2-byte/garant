"""Crystalpay v3 async client.

Hits the upstream API via an ``httpx.MockTransport`` so the tests
exercise the real ``Crystalpay`` HTTP code path (request shape,
response parsing, error surfacing) without touching the network.
"""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from backend.app.crystalpay import (
    INVOICE_STATE_PAID,
    INVOICE_STATE_UNAVAILABLE,
    Crystalpay,
    CrystalpayError,
    verify_webhook_signature,
)


def _make_client(handler):
    transport = httpx.MockTransport(handler)
    cp = Crystalpay("login", "secret")
    cp._client = httpx.AsyncClient(base_url="https://api.crystalpay.io/v3", transport=transport)
    return cp


@pytest.mark.asyncio
async def test_create_invoice_sends_auth_and_returns_parsed_invoice():
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.append({"url": str(request.url), "body": body})
        return httpx.Response(
            200,
            json={
                "error": False,
                "id": "inv-1",
                "url": "https://pay.crystalpay.io/inv-1",
                "state": "created",
                "type": "purchase",
                "amount": "10.00",
                "currency": "USDT",
            },
        )

    cp = _make_client(handler)
    inv = await cp.create_invoice(amount=10.0, currency="USDT", lifetime=15, description="t")
    await cp._client.aclose()

    assert inv.id == "inv-1"
    assert inv.url == "https://pay.crystalpay.io/inv-1"
    assert inv.state == "created"
    assert captured[0]["url"].endswith("/invoice/create/")
    sent = captured[0]["body"]
    assert sent["auth_login"] == "login"
    assert sent["auth_secret"] == "secret"
    assert sent["amount"] == "10.0"
    assert sent["currency"] == "USDT"
    assert sent["lifetime"] == 15


@pytest.mark.asyncio
async def test_get_invoice_returns_state_from_envelope():
    def handler(request: httpx.Request) -> httpx.Response:
        # Crystalpay sometimes wraps the invoice in a ``response``
        # envelope; the client must unwrap both shapes.
        return httpx.Response(
            200,
            json={
                "error": False,
                "response": {
                    "id": "inv-9",
                    "url": "https://pay/x",
                    "state": INVOICE_STATE_PAID,
                },
            },
        )

    cp = _make_client(handler)
    inv = await cp.get_invoice("inv-9")
    await cp._client.aclose()

    assert inv.id == "inv-9"
    assert inv.state == INVOICE_STATE_PAID


@pytest.mark.asyncio
async def test_create_invoice_raises_on_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "error": True,
                "errors": ["Auth failed", "Cashbox locked"],
            },
        )

    cp = _make_client(handler)
    with pytest.raises(CrystalpayError) as exc_info:
        await cp.create_invoice(amount=1.0)
    await cp._client.aclose()
    assert "Auth failed" in str(exc_info.value)
    assert "Cashbox locked" in str(exc_info.value)


@pytest.mark.asyncio
async def test_create_invoice_raises_on_non_json_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"<html>boom</html>")

    cp = _make_client(handler)
    with pytest.raises(CrystalpayError):
        await cp.create_invoice(amount=1.0)
    await cp._client.aclose()


@pytest.mark.asyncio
async def test_crystalpay_raises_on_empty_credentials():
    with pytest.raises(CrystalpayError):
        Crystalpay("", "secret")
    with pytest.raises(CrystalpayError):
        Crystalpay("login", "")


def test_verify_webhook_signature_accepts_valid_signature():
    expected = hashlib.sha1(b"inv-42:secret-salt").hexdigest()
    assert verify_webhook_signature("inv-42", "secret-salt", expected) is True


def test_verify_webhook_signature_rejects_tampered_signature():
    assert verify_webhook_signature("inv-42", "secret-salt", "deadbeef") is False


def test_verify_webhook_signature_rejects_empty_inputs():
    expected = hashlib.sha1(b"inv-42:secret-salt").hexdigest()
    assert verify_webhook_signature("", "secret-salt", expected) is False
    assert verify_webhook_signature("inv-42", "", expected) is False
    assert verify_webhook_signature("inv-42", "secret-salt", None) is False


def test_verify_webhook_signature_rejects_wrong_salt():
    expected = hashlib.sha1(b"inv-42:secret-salt").hexdigest()
    assert verify_webhook_signature("inv-42", "wrong-salt", expected) is False


def test_create_invoice_state_unavailable_is_terminal():
    # Smoke-test the constants; the rest of the system imports them
    # by name so a typo would mis-route the webhook handlers.
    assert INVOICE_STATE_UNAVAILABLE == "unavailable"
    assert INVOICE_STATE_PAID == "payed"
