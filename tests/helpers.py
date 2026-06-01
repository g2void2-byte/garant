"""Test helpers: signed initData, auth headers, fixture data setup."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import time
from urllib.parse import urlencode

from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def tiny_image_bytes(fmt: str = "PNG", size: tuple[int, int] = (1, 1)) -> bytes:
    """Return a minimal but *valid* image of the requested Pillow format.

    The ``/api/media/upload`` route re-encodes incoming payloads through
    Pillow (L-5 defensive sieve), so test fixtures need to ship bodies
    that decode cleanly rather than hand-rolled 8-byte magic-byte stubs.
    Keeping the generator in one place means the format/mode quirks
    (JPEG having no alpha, GIF needing ``P`` mode, …) only have to be
    settled once.
    """
    mode = "RGB" if fmt.upper() in ("JPEG", "GIF") else "RGBA"
    img = Image.new(mode, size, color=(255, 0, 0) if mode == "RGB" else (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format=fmt.upper())
    return buf.getvalue()


def signed_init_data(
    tg_user_id: int,
    username: str = "user",
    *,
    language_code: str | None = None,
) -> str:
    """Build a Telegram WebApp initData string signed with the test bot token.

    Mirrors the algorithm in ``backend.app.security.verify_init_data``:
    sort fields, HMAC-SHA256 over the key derived from ``"WebAppData"`` +
    bot_token.

    ``language_code`` is the IETF tag Telegram nests inside the ``user``
    payload (e.g. ``"ru"``, ``"en"``). Tests targeting the A-6 cohort
    filters pass it through here so the resulting initData round-trips
    into ``users.language_code``.
    """
    from backend.app.config import settings

    user_payload: dict[str, object] = {
        "id": tg_user_id,
        "first_name": username,
        "username": username,
    }
    if language_code is not None:
        user_payload["language_code"] = language_code
    user = json.dumps(user_payload, separators=(",", ":"))
    auth_date = str(int(time.time()))
    items = sorted([("auth_date", auth_date), ("user", user)])
    data_check_string = "\n".join(f"{k}={v}" for k, v in items)
    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({"user": user, "auth_date": auth_date, "hash": h})


def auth_headers(init_data: str) -> dict[str, str]:
    return {"Authorization": f"tma {init_data}"}


# V12-H1 — read the live ``ADMIN_TOTP_BYPASS`` value the conftest
# generated for this pytest invocation. The previous module-level
# constant string is gone; the sentinel is now a random per-run value
# that never escapes the test process. Sending it as ``X-Totp-Code``
# short-circuits ``require_totp`` so tests can hit 2FA-gated admin
# endpoints without provisioning a real secret. Tests in
# ``test_admin_misc.py`` that exercise the *real* TOTP flow avoid
# this helper and go through ``/api/admin/2fa/enable`` instead.
def _totp_bypass_code() -> str:
    """Return the active TOTP bypass sentinel.

    Read from the env at call time (not at import) so a test that
    uses ``monkeypatch.setenv("ADMIN_TOTP_BYPASS", "...")`` to verify
    the per-request re-read behaviour (V5-A-9) doesn't desync its
    own helper from the value the server sees.
    """
    return os.environ["ADMIN_TOTP_BYPASS"]


def with_totp(headers: dict[str, str]) -> dict[str, str]:
    """Augment ``headers`` with the TOTP-bypass header for tests that
    hit a now-2FA-gated admin endpoint."""
    return {**headers, "X-Totp-Code": _totp_bypass_code()}


# V5-A-4 (M) — the production blacklist (``backend.app.pin.COMMON_PINS``)
# rejects 1234/1111/0000/etc at /setup. Tests that don't care about the
# PIN value go through this helper and get a strong default so they
# don't have to track which entries the blacklist covers.
STRONG_TEST_PIN = "3741"


async def setup_pin(client: AsyncClient, init_data: str, pin: str = STRONG_TEST_PIN) -> str:
    """Bootstrap a user (POST /api/pin/setup creates the User row) and
    return the X-Pin-Token for PIN-gated endpoints."""
    resp = await client.post("/api/pin/setup", json={"pin": pin}, headers=auth_headers(init_data))
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


async def get_user_id_by_tg(session: AsyncSession, tg_user_id: int) -> int:
    from backend.app.models import User

    result = await session.execute(select(User).where(User.tg_user_id == tg_user_id))
    return result.scalar_one().id


async def credit_balance(session: AsyncSession, user_id: int, code: str, amount: float) -> None:
    """Directly credit a user's spendable balance for a currency.

    Bypasses CryptoBot — used to give buyers escrow funds without
    going through the real deposit flow.
    """
    from backend.app.services_wallet import (
        get_currency_by_code,
        get_or_create_balance,
    )

    cur = await get_currency_by_code(session, code)
    bal = await get_or_create_balance(session, user_id, cur.id)
    bal.amount = float(amount)
    await session.commit()


async def ensure_admin_user(
    client: AsyncClient,
    *,
    tg_user_id: int = 990001,
    username: str = "ops_admin",
) -> int:
    """Create or promote one admin so manual operational paths exist in tests."""
    from backend.app.db import async_session
    from backend.app.models import User

    init = signed_init_data(tg_user_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    admin_id = int(resp.json()["id"])
    async with async_session() as session:
        admin = await session.get(User, admin_id)
        assert admin is not None
        admin.is_admin = True
        await session.commit()
    return admin_id
