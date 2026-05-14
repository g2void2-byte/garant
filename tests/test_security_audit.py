"""Regression tests for the security audit fixes.

Covers four issues raised in the audit pass and patched in this PR:

* **Account-transfer brute-force** — the 6-digit one-time code is
  shared across the keyspace, so the confirm endpoint must rate-limit
  attempts *and* burn codes after a small number of misses.
* **CryptoBot webhook fail-open** — when ``CRYPTOBOT_TOKEN`` is empty
  the webhook must refuse the request, not silently accept it.
* **Media upload XSS** — the saved extension comes from the validated
  content-type, never from the user-supplied filename.
* **CORS wildcard fallback** — booting with an empty
  ``ALLOWED_ORIGINS`` must fail instead of installing ``allow_origins
  = ["*"]`` alongside ``allow_credentials = True``.
"""

from __future__ import annotations

import importlib
import json

import pytest
from sqlalchemy import select

from tests.helpers import (
    auth_headers,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)

# ── 1. Account-transfer brute-force protection ────────────────────────────


async def _issue_transfer_code(client, source_init: str, tg_user_id: int) -> str:
    """Issue a fresh transfer code for ``tg_user_id`` and return its
    plaintext. The HTTP endpoint only delivers the code via the bot, so
    for deterministic tests we drive the service layer directly.
    """
    from backend.app.db import async_session
    from backend.app.models import User
    from backend.app.services_account import issue_code

    await setup_pin(client, source_init)  # bootstraps the source row

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, tg_user_id)
        source = await session.get(User, user_id)
        assert source is not None
        code, _expires = await issue_code(session, source)
    return code


async def test_transfer_confirm_burns_code_after_few_misses(client):
    """Brute-forcing wrong codes must invalidate every live code quickly."""
    from backend.app.db import async_session
    from backend.app.models import AccountTransferCode
    from backend.app.services_account import MAX_CONFIRM_ATTEMPTS

    source_init = signed_init_data(9101, "source")
    real_code = await _issue_transfer_code(client, source_init, 9101)

    attacker_init = signed_init_data(9102, "attacker")
    # Bootstrap the attacker user row.
    resp = await client.get("/api/me", headers=auth_headers(attacker_init))
    assert resp.status_code == 200

    # Burn just under the cap with wrong codes — code must still be live.
    for i in range(MAX_CONFIRM_ATTEMPTS - 1):
        wrong = f"{(int(real_code) + i + 1) % 1_000_000:06d}"
        if wrong == real_code:
            wrong = "000000" if real_code != "000000" else "111111"
        resp = await client.post(
            "/api/account/transfer/confirm",
            json={"code": wrong},
            headers=auth_headers(attacker_init),
        )
        assert resp.status_code == 400

    async with async_session() as session:
        row = (await session.execute(select(AccountTransferCode))).scalar_one()
        assert row.consumed_at is None
        assert row.attempts == MAX_CONFIRM_ATTEMPTS - 1

    # One more miss crosses the threshold and burns the code.
    bad = "000000" if real_code != "000000" else "111111"
    resp = await client.post(
        "/api/account/transfer/confirm",
        json={"code": bad},
        headers=auth_headers(attacker_init),
    )
    assert resp.status_code == 400

    async with async_session() as session:
        row = (await session.execute(select(AccountTransferCode))).scalar_one()
        assert row.consumed_at is not None, "code must be consumed after threshold"

    # Reset the per-caller rate-limit window before the last probe so we
    # exercise the in-DB consumption check and not the RLPin 429.
    from backend.app.rate_limit import reset_state_for_tests

    reset_state_for_tests()

    # Even the correct code now bounces because the row is no longer live.
    resp = await client.post(
        "/api/account/transfer/confirm",
        json={"code": real_code},
        headers=auth_headers(attacker_init),
    )
    assert resp.status_code == 400


async def test_transfer_confirm_rate_limit_applied(client):
    """RLPin is wired up — confirm should 429 past 5/minute."""
    from backend.app.rate_limit import reset_state_for_tests

    reset_state_for_tests()

    attacker_init = signed_init_data(9201, "rl-attacker")
    resp = await client.get("/api/me", headers=auth_headers(attacker_init))
    assert resp.status_code == 200

    statuses: list[int] = []
    for _ in range(7):
        resp = await client.post(
            "/api/account/transfer/confirm",
            json={"code": "000000"},
            headers=auth_headers(attacker_init),
        )
        statuses.append(resp.status_code)

    # First few are 400 (bad code); somewhere after the 5th, the limiter
    # kicks in with 429.
    assert 429 in statuses, statuses


# ── 2. CryptoBot webhook fail-closed when token is unset ──────────────────


async def test_webhook_refuses_when_token_unset(client, monkeypatch):
    """An empty CRYPTOBOT_TOKEN must NOT let unauthenticated callers in."""
    from backend.app.routers import payments as payments_router

    monkeypatch.setattr(payments_router, "webhook_secret", lambda: "")

    body = json.dumps({"update_type": "invoice_paid", "payload": {"invoice_id": "x"}}).encode()
    resp = await client.post(
        "/api/payments/webhook/cryptobot",
        content=body,
        headers={
            "crypto-pay-api-signature": "anything",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 503


# ── 3. Media upload — extension is content-type derived ───────────────────


async def test_media_upload_rejects_html_disguised_as_image(client):
    """A client uploading ``evil.html`` with an image content-type must
    still get a safe, image-only extension on disk — the saved file
    must not be ``.html``."""
    from backend.app.db import async_session
    from backend.app.models import Media

    init_data = signed_init_data(9301, "uploader")
    await setup_pin(client, init_data)  # bootstraps the user row

    files = {"file": ("evil.html", b"\x89PNG\r\n\x1a\n", "image/png")}
    data = {"kind": "avatar"}
    resp = await client.post(
        "/api/media/upload", data=data, files=files, headers=auth_headers(init_data)
    )
    assert resp.status_code == 201, resp.text

    payload = resp.json()
    assert payload["url"].endswith(".png"), payload
    assert ".html" not in payload["url"]

    async with async_session() as session:
        m = (await session.execute(select(Media))).scalar_one()
        assert not m.url.endswith(".html")
        assert m.url.endswith(".png")


async def test_media_upload_rejects_unknown_content_type(client):
    """Non-image content-types are now refused for every ``kind``,
    including ``deal`` which previously accepted anything."""
    init_data = signed_init_data(9302, "uploader2")
    await setup_pin(client, init_data)

    files = {"file": ("payload.html", b"<script>1</script>", "text/html")}
    data = {"kind": "deal"}
    resp = await client.post(
        "/api/media/upload", data=data, files=files, headers=auth_headers(init_data)
    )
    assert resp.status_code == 415, resp.text


# ── 4. CORS — wildcard fallback removed ───────────────────────────────────


def test_main_refuses_empty_allowed_origins(monkeypatch):
    """Importing ``backend.app.main`` with empty ALLOWED_ORIGINS must
    raise — we no longer fall back to ``["*"]``."""
    from backend.app import config

    monkeypatch.setattr(config.settings, "allowed_origins", "")

    import backend.app.main as main_module

    with pytest.raises(RuntimeError, match="ALLOWED_ORIGINS"):
        importlib.reload(main_module)

    # Reload back to the conftest default so other tests stay healthy.
    monkeypatch.setattr(config.settings, "allowed_origins", "http://localhost:5173")
    importlib.reload(main_module)
