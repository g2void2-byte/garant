"""Test helpers: signed initData, auth headers, fixture data setup."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def signed_init_data(tg_user_id: int, username: str = "user") -> str:
    """Build a Telegram WebApp initData string signed with the test bot token.

    Mirrors the algorithm in ``backend.app.security.verify_init_data``:
    sort fields, HMAC-SHA256 over the key derived from ``"WebAppData"`` +
    bot_token.
    """
    from backend.app.config import settings

    user = json.dumps(
        {"id": tg_user_id, "first_name": username, "username": username},
        separators=(",", ":"),
    )
    auth_date = str(int(time.time()))
    items = sorted([("auth_date", auth_date), ("user", user)])
    data_check_string = "\n".join(f"{k}={v}" for k, v in items)
    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({"user": user, "auth_date": auth_date, "hash": h})


def auth_headers(init_data: str) -> dict[str, str]:
    return {"Authorization": f"tma {init_data}"}


# Pre-shared sentinel that the conftest installs as ``ADMIN_TOTP_BYPASS``.
# Sending it as ``X-Totp-Code`` short-circuits ``require_totp`` so tests
# can hit 2FA-gated admin endpoints without provisioning a real secret.
# Tests in ``test_admin_misc.py`` that exercise the *real* TOTP flow
# avoid this helper and go through ``/api/admin/2fa/enable`` instead.
TOTP_BYPASS_CODE = "test-totp-bypass-do-not-use-in-prod"


def with_totp(headers: dict[str, str]) -> dict[str, str]:
    """Augment ``headers`` with the TOTP-bypass header for tests that
    hit a now-2FA-gated admin endpoint."""
    return {**headers, "X-Totp-Code": TOTP_BYPASS_CODE}


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
