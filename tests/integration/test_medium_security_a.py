"""Regression tests for PR-A (5 Medium-severity security findings).

* **M-1** — ``verify_init_data`` must raise ``InitDataError`` on a
  non-numeric ``auth_date`` instead of letting ``ValueError`` escape
  and surface as HTTP 500.
* **M-13** — ``/api/support/admins`` and ``/api/support/arbiters``
  must require auth (no anonymous enumeration of privileged users).
* **M-14** — ``/api/categories`` must require auth.
* **M-15** — ``/api/reviews?user=...`` must require auth and accept
  ``limit``/``offset`` so we don't return every review of a popular
  profile in one shot.
* **M-21** — ``pin_secret()`` must refuse to fall back to a
  ``bot_token``-derived hash when ``ENVIRONMENT=production`` (or
  ``staging``). The fallback is dev-only.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from backend.app import config as config_module
from backend.app.config import settings as app_settings
from backend.app.db import async_session
from backend.app.models import Review, User
from backend.app.security import InitDataError, verify_init_data
from tests.helpers import auth_headers, signed_init_data

# ── M-1 — non-numeric auth_date ────────────────────────────────────────────


def _signed_init_data_with_raw_auth_date(tg_user_id: int, auth_date: str, username: str) -> str:
    """Build a token with arbitrary ``auth_date`` text and a valid HMAC."""
    user = json.dumps(
        {"id": tg_user_id, "first_name": username, "username": username},
        separators=(",", ":"),
    )
    items = sorted([("auth_date", auth_date), ("user", user)])
    data_check_string = "\n".join(f"{k}={v}" for k, v in items)
    secret_key = hmac.new(b"WebAppData", app_settings.bot_token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({"user": user, "auth_date": auth_date, "hash": h})


def test_verify_init_data_non_numeric_auth_date_raises_init_data_error():
    """Pre-fix this raised ``ValueError`` and bubbled up as HTTP 500."""
    if app_settings.allow_unsigned_init_data:
        pytest.skip("HMAC bypassed in this test config; M-1 path not reachable")
    init = _signed_init_data_with_raw_auth_date(9201, "not-a-number", "m1_bad")
    with pytest.raises(InitDataError) as exc:
        verify_init_data(init)
    assert "numeric" in str(exc.value).lower() or "auth_date" in str(exc.value).lower()


async def test_api_returns_401_for_non_numeric_auth_date(client):
    """End-to-end: malformed ``auth_date`` lands on 401, not 500."""
    if app_settings.allow_unsigned_init_data:
        pytest.skip("HMAC bypassed in this test config; M-1 path not reachable")
    init = _signed_init_data_with_raw_auth_date(9202, "abc123", "m1_api")
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 401, resp.text


# ── M-13 — support/admins, support/arbiters need auth ─────────────────────


async def test_support_admins_requires_auth(client):
    # Audit (continuation) H-3 — missing Authorization header now
    # surfaces a clean 401 from ``get_current_user`` (pre-fix this
    # leaked a 422 with Pydantic's required-header validator body).
    resp = await client.get("/api/support/admins")
    assert resp.status_code == 401
    # Invalid scheme → 401.
    resp = await client.get("/api/support/admins", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


async def test_support_arbiters_requires_auth(client):
    resp = await client.get("/api/support/arbiters")
    assert resp.status_code == 401  # Audit cont. H-3
    resp = await client.get("/api/support/arbiters", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


async def test_support_admins_works_with_auth(client):
    init = signed_init_data(9301, "m13_caller")
    resp = await client.get("/api/support/admins", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


async def test_support_arbiters_works_with_auth(client):
    init = signed_init_data(9302, "m13_caller2")
    resp = await client.get("/api/support/arbiters", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


# ── M-14 — categories listing needs auth ──────────────────────────────────


async def test_categories_requires_auth(client):
    resp = await client.get("/api/categories")
    assert resp.status_code == 401  # Audit cont. H-3
    resp = await client.get("/api/categories", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


async def test_categories_works_with_auth(client):
    init = signed_init_data(9401, "m14_caller")
    resp = await client.get("/api/categories", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


# ── M-15 — reviews list: auth + pagination ────────────────────────────────


async def _seed_reviews(target_username: str, count: int) -> None:
    """Insert ``count`` reviews directly. ``Review.deal_id`` is nullable
    so we skip the deal scaffolding the service-layer path needs."""
    async with async_session() as session:
        target = User(
            tg_user_id=9501,
            username=target_username,
            display_name="m15 target",
        )
        author = User(
            tg_user_id=9502,
            username="m15_author",
            display_name="m15 author",
        )
        session.add_all([target, author])
        await session.flush()

        for i in range(count):
            session.add(
                Review(
                    deal_id=None,
                    author_id=author.id,
                    target_id=target.id,
                    rating=5,
                    text=f"m15-review-{i}",
                )
            )
        await session.commit()


async def test_reviews_list_requires_auth(client):
    resp = await client.get("/api/reviews", params={"user": "anyone"})
    assert resp.status_code == 401  # Audit cont. H-3
    resp = await client.get(
        "/api/reviews",
        params={"user": "anyone"},
        headers={"Authorization": "Bearer nope"},
    )
    assert resp.status_code == 401


async def test_reviews_list_pagination_caps_returned_rows(client):
    """A profile with 12 reviews queried with ``limit=5`` returns 5."""
    await _seed_reviews("m15_target", 12)

    caller_init = signed_init_data(9503, "m15_caller")
    resp = await client.get(
        "/api/reviews",
        params={"user": "m15_target", "limit": 5},
        headers=auth_headers(caller_init),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 5


async def test_reviews_list_rejects_oversized_limit(client):
    """``limit > 100`` is rejected by FastAPI's query validation."""
    caller_init = signed_init_data(9504, "m15_caller2")
    resp = await client.get(
        "/api/reviews",
        params={"user": "anyone", "limit": 500},
        headers=auth_headers(caller_init),
    )
    assert resp.status_code == 422


# ── M-21 — pin_secret fail-fast in production ─────────────────────────────


def test_pin_secret_returns_explicit_secret_when_set(monkeypatch):
    """When ``PIN_JWT_SECRET`` is set we always return it verbatim."""
    monkeypatch.setattr(config_module.settings, "pin_jwt_secret", "explicit-secret")
    monkeypatch.setattr(config_module.settings, "environment", "production")
    assert config_module.pin_secret() == "explicit-secret"


def test_pin_secret_falls_back_in_dev(monkeypatch):
    """Dev / test default keeps the existing fallback so local runs
    don't need a separate secret in ``.env``."""
    monkeypatch.setattr(config_module.settings, "pin_jwt_secret", "")
    monkeypatch.setattr(config_module.settings, "environment", "development")
    monkeypatch.setattr(config_module.settings, "bot_token", "abc")
    out = config_module.pin_secret()
    expected = hashlib.sha256(b"pin-jwt:" + b"abc").hexdigest()
    assert out == expected


def test_pin_secret_falls_back_in_test(monkeypatch):
    monkeypatch.setattr(config_module.settings, "pin_jwt_secret", "")
    monkeypatch.setattr(config_module.settings, "environment", "test")
    monkeypatch.setattr(config_module.settings, "bot_token", "abc")
    out = config_module.pin_secret()
    expected = hashlib.sha256(b"pin-jwt:" + b"abc").hexdigest()
    assert out == expected


def test_pin_secret_refuses_to_derive_in_production(monkeypatch):
    """No fallback when ``ENVIRONMENT=production`` and the secret is
    not configured — fail loudly during startup instead of silently
    signing JWTs with a bot-token-derived key."""
    monkeypatch.setattr(config_module.settings, "pin_jwt_secret", "")
    monkeypatch.setattr(config_module.settings, "environment", "production")
    with pytest.raises(RuntimeError) as exc:
        config_module.pin_secret()
    assert "PIN_JWT_SECRET" in str(exc.value)


def test_pin_secret_refuses_to_derive_in_staging(monkeypatch):
    monkeypatch.setattr(config_module.settings, "pin_jwt_secret", "")
    monkeypatch.setattr(config_module.settings, "environment", "staging")
    with pytest.raises(RuntimeError):
        config_module.pin_secret()
