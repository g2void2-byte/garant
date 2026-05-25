"""Regression tests for the PR C medium concurrency / validation fixes:

* **M-4** ``_get_or_create_user`` race — concurrent bot menu callbacks
  for the same Telegram user must not raise ``IntegrityError`` on
  ``users.tg_user_id`` uniqueness.
* **M-7** ``pin_reset_confirm`` brute-force — wrong reset codes must
  increment ``pin_attempts`` and lock the user after ``pin_max_attempts``.
* **M-8** ``REDIS_URL`` empty in production — the lifespan startup
  must refuse to boot when ``ENVIRONMENT`` is ``production`` or
  ``staging``.
* **M-22** ``create_service`` active-services-limit race — two parallel
  ``POST /api/services`` calls must not both pass the ``active < max``
  check.

Together with the prior ``test_critical_race_conditions`` suite this
exercises the row-level locking and ON-CONFLICT patterns used to
serialise multi-row state changes.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select

from tests.helpers import auth_headers, setup_pin, signed_init_data

# ── M-4 — _get_or_create_user race ─────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_bot_callbacks_do_not_race_user_insert():
    """M-4 — two ``_get_or_create_user`` calls for the same tg_user_id
    against an empty users table must both return the same User row
    without raising ``IntegrityError`` on the ``tg_user_id`` unique
    constraint.

    Before the fix the check-then-insert pattern raced; with
    ``INSERT ... ON CONFLICT DO NOTHING`` the loser falls through to
    a second ``SELECT`` and still observes the row inserted by the
    winner.
    """
    from backend.app.bot.sections import _get_or_create_user
    from backend.app.db import async_session
    from backend.app.models import User

    tg_id = 81001

    async def call() -> int:
        async with async_session() as session:
            user = await _get_or_create_user(session, tg_id, username="m4_race", first_name="Race")
            return user.id

    id_a, id_b = await asyncio.gather(call(), call())
    assert id_a == id_b

    async with async_session() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(User).where(User.tg_user_id == tg_id)
            )
        ).scalar_one()
        assert count == 1


# ── M-7 — brute-force protection on pin_reset_confirm ──────────────────


@pytest.mark.asyncio
async def test_pin_reset_confirm_locks_after_max_wrong_codes(client, monkeypatch):
    """M-7 — wrong reset codes must increment ``pin_attempts`` and lock
    the user once ``pin_max_attempts`` is reached, same behaviour as
    ``/api/pin/check`` for wrong PINs.

    Before the fix wrong reset codes returned 401 forever, so an
    attacker could enumerate the 6-digit reset-code keyspace.
    """
    from backend.app.config import settings
    from backend.app.db import async_session
    from backend.app.models import User

    # Make the test independent of prod tuning.
    monkeypatch.setattr(settings, "pin_max_attempts", 3, raising=False)

    init = signed_init_data(81101, "m7_user")
    await setup_pin(client, init)

    # Seed a reset code row directly so we don't rely on the rate-limited
    # /api/pin/reset/request endpoint.
    from datetime import timedelta

    from backend.app.pin import hash_reset_code
    from backend.app.routers.pin import _now

    async with async_session() as session:
        user = (await session.execute(select(User).where(User.tg_user_id == 81101))).scalar_one()
        user.pin_reset_code_hash = hash_reset_code("123456")
        user.pin_reset_expires = _now() + timedelta(minutes=10)
        user.pin_attempts = 0
        user.pin_locked_until = None
        await session.commit()

    headers = auth_headers(init)
    body = {"code": "000000", "new_pin": "9999"}

    # First (max-1) wrong codes return 401.
    for _ in range(settings.pin_max_attempts - 1):
        r = await client.post("/api/pin/reset/confirm", json=body, headers=headers)
        assert r.status_code == 401, r.text

    # The final wrong code trips the lockout (HTTP 423).
    r = await client.post("/api/pin/reset/confirm", json=body, headers=headers)
    assert r.status_code == 423, r.text

    # And the user row reflects the lock.
    async with async_session() as session:
        user = (await session.execute(select(User).where(User.tg_user_id == 81101))).scalar_one()
        assert user.pin_locked_until is not None
        assert user.pin_locked_until > _now()


# ── M-8 — REDIS_URL required in production / staging ────────────────────


@pytest.mark.asyncio
async def test_lifespan_refuses_to_boot_in_production_without_redis_url(monkeypatch):
    """M-8 — with ``ENVIRONMENT=production`` and an empty ``REDIS_URL``
    the FastAPI ``lifespan`` must raise ``RuntimeError`` rather than
    silently fall back to per-process in-memory rate-limit counters.

    Multi-worker uvicorn deployments turn that fallback into an
    ``N × configured`` effective limit, which defeats the whole point
    of the limiter.
    """
    from backend.app.config import settings
    from backend.app.main import app, lifespan

    monkeypatch.setattr(settings, "environment", "production", raising=False)
    monkeypatch.setattr(settings, "redis_url", "", raising=False)

    with pytest.raises(RuntimeError, match="REDIS_URL"):
        async with lifespan(app):
            pass


@pytest.mark.asyncio
async def test_lifespan_refuses_to_boot_in_staging_without_redis_url(monkeypatch):
    """M-8 — same as production: staging must also fail-closed."""
    from backend.app.config import settings
    from backend.app.main import app, lifespan

    monkeypatch.setattr(settings, "environment", "staging", raising=False)
    monkeypatch.setattr(settings, "redis_url", "", raising=False)

    with pytest.raises(RuntimeError, match="REDIS_URL"):
        async with lifespan(app):
            pass


# ── M-22 — create_service active-limit race ─────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_service_create_respects_active_limit(client, monkeypatch):
    """M-22 — two parallel ``POST /api/services`` must not both pass
    the ``active < max_active`` check when the limit is already at
    ``max - 1``.

    Before the fix two concurrent requests could both count ``max - 1``
    active services and both insert, leaving the user with ``max + 1``
    active services. The ``FOR UPDATE`` lock on the user row
    serialises the two requests so only one succeeds.
    """
    from backend.app.db import async_session
    from backend.app.models import AppSettings, Category, Service, ServiceStatus, User

    init = signed_init_data(81201, "m22_seller")
    await setup_pin(client, init)

    # Configure a small active-limit and seed exactly ``max - 1``
    # active services so the two concurrent inserts both sit on the
    # boundary.
    async with async_session() as session:
        s = (await session.execute(select(AppSettings).limit(1))).scalar_one_or_none()
        if s is None:
            s = AppSettings()
            session.add(s)
        s.max_active_services_per_user = 2
        cat = (await session.execute(select(Category).limit(1))).scalar_one()
        user = (await session.execute(select(User).where(User.tg_user_id == 81201))).scalar_one()
        session.add(
            Service(
                owner_id=user.id,
                category_id=cat.id,
                title="seed service",
                description="",
                price=10.0,
                status=ServiceStatus.active,
            )
        )
        await session.commit()
        category_slug = cat.slug

    headers = auth_headers(init)
    body = {
        "title": "race service",
        "description": "race",
        "price": 20.0,
        "category_slug": category_slug,
    }

    r1, r2 = await asyncio.gather(
        client.post("/api/services", json=body, headers=headers),
        client.post("/api/services", json=body, headers=headers),
    )

    statuses = sorted([r1.status_code, r2.status_code])
    # One succeeds (200/201), the other hits the active-limit guard (400).
    assert 400 in statuses, (r1.status_code, r1.text, r2.status_code, r2.text)
    assert any(s in (200, 201) for s in statuses), (r1.status_code, r2.status_code)

    async with async_session() as session:
        user = (await session.execute(select(User).where(User.tg_user_id == 81201))).scalar_one()
        active = (
            await session.execute(
                select(func.count())
                .select_from(Service)
                .where(
                    Service.owner_id == user.id,
                    Service.status == ServiceStatus.active,
                )
            )
        ).scalar_one()
        assert active == 2
