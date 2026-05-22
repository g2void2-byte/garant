"""Pins every "simple" audit follow-up fix landed in the
``devin/audit-all-simple`` round.

* **§4.4** — confirm ``ix_users_last_login_at`` actually exists in the
  test DB so the ``_audience_filter`` btree path is real, not just a
  ``models.py`` ``index=True`` claim. The supplementary migration
  ``c8f4a2e91d35`` carries the explicit ``CREATE INDEX CONCURRENTLY``
  call.

* **§4.5** — when ``settings.require_redis_for_2fa`` is on AND Redis
  is unavailable, ``_store_pending`` returns 503 instead of silently
  falling back to the in-process ``_pending_secrets`` dict. Production
  scale-out deploys flip this flag so the misconfiguration surfaces on
  the very first enrolment attempt instead of hours later when a
  second worker can't find the secret.

* **§15.8** — the legacy-DealStatus drop migration now does a
  pre-flight ``SELECT count(*) ... WHERE status::text = ANY(...)`` and
  raises a friendly ``RuntimeError`` if any row still holds a legacy
  value. Pre-fix the bare ``ALTER TYPE`` died with PG's cryptic
  ``invalid input value for enum`` error.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import fakeredis.aioredis
import pytest
from sqlalchemy import text

from backend.app import redis_client
from backend.app.config import settings
from backend.app.db import async_session
from backend.app.models import User
from tests.helpers import auth_headers, signed_init_data

# ── §4.4 — ix_users_last_login_at index ────────────────────────────


async def test_4_4_users_last_login_at_index_exists(client):
    """``admin/broadcasts._audience_filter`` builds
    ``WHERE users.last_login_at >= since`` for the ``audience_active_days``
    cohort. Without a btree on ``last_login_at`` PG falls back to a
    sequential scan which kills performance on real user-table sizes.

    The audit (§4.4) couldn't tell from models alone whether the
    migration actually created the index. This test pins it: the
    physical index must be present in the test DB (which runs the
    full migration chain in ``conftest.py``).
    """
    async with async_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'users' AND indexname = 'ix_users_last_login_at'"
                )
            )
        ).first()

    assert row is not None, (
        "ix_users_last_login_at is missing from the test DB — broadcasts "
        "audience_active_days filter will sequential-scan the users table"
    )


# ── §4.5 — require_redis_for_2fa fails loud instead of in-process fallback ──


@pytest.fixture
async def no_redis():
    """Force ``get_redis()`` to return None for the duration of a test."""
    redis_client.override_for_tests(None)
    # Marking ``_resolved`` true via re-binding means the lazy first-call
    # path doesn't try to reach a real redis server.
    yield
    redis_client.override_for_tests(None)


async def test_4_5_setup_returns_503_when_redis_required_but_missing(client, monkeypatch, no_redis):
    """``POST /api/admin/2fa/setup`` returns 503 when
    ``require_redis_for_2fa`` is on and Redis is unavailable, instead
    of silently writing to the per-process ``_pending_secrets`` dict."""
    monkeypatch.setattr(settings, "require_redis_for_2fa", True)

    # Force ``get_redis()`` to return None even though the module may
    # have a cached client from earlier tests in the run.
    async def _no_redis() -> None:
        return None

    monkeypatch.setattr(
        "backend.app.routers.admin.twofa.get_redis",
        _no_redis,
    )

    init = signed_init_data(91234, "audit45user")
    # Bootstrap the user via the normal ``/api/me`` flow, then flip the
    # admin bit directly in the DB (same shape ``_make_admin`` uses
    # everywhere else in the test suite).
    me = await client.get("/api/me", headers=auth_headers(init))
    assert me.status_code == 200, me.text
    uid = me.json()["id"]
    async with async_session() as session:
        u = await session.get(User, uid)
        assert u is not None
        u.is_admin = True
        await session.commit()

    r = await client.post("/api/admin/2fa/setup", headers=auth_headers(init))
    assert r.status_code == 503, r.text
    body = r.json()
    assert "Redis" in body.get("detail", ""), body


async def test_4_5_setup_falls_back_when_flag_unset(client, monkeypatch, no_redis):
    """The default (``require_redis_for_2fa=False``) still permits the
    in-process fallback so dev / single-replica deployments keep
    working. This pins the backward-compat default."""
    monkeypatch.setattr(settings, "require_redis_for_2fa", False)

    async def _no_redis() -> None:
        return None

    monkeypatch.setattr(
        "backend.app.routers.admin.twofa.get_redis",
        _no_redis,
    )
    # Reset the one-shot warning so the fallback path runs cleanly.
    from backend.app.routers.admin import twofa as twofa_mod

    twofa_mod._reset_fallback_warn_for_tests()

    init = signed_init_data(91235, "audit45fallback")
    me = await client.get("/api/me", headers=auth_headers(init))
    assert me.status_code == 200, me.text
    uid = me.json()["id"]
    async with async_session() as session:
        u = await session.get(User, uid)
        assert u is not None
        u.is_admin = True
        await session.commit()

    r = await client.post("/api/admin/2fa/setup", headers=auth_headers(init))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("secret"), body


async def test_4_5_setup_works_when_redis_required_and_present(client, monkeypatch):
    """With ``require_redis_for_2fa`` on AND a working Redis,
    ``/setup`` succeeds (the flag is a no-op on the happy path)."""
    monkeypatch.setattr(settings, "require_redis_for_2fa", True)

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_client.override_for_tests(fake)
    try:
        init = signed_init_data(91236, "audit45okredis")
        me = await client.get("/api/me", headers=auth_headers(init))
        assert me.status_code == 200, me.text
        uid = me.json()["id"]
        async with async_session() as session:
            u = await session.get(User, uid)
            assert u is not None
            u.is_admin = True
            await session.commit()

        r = await client.post("/api/admin/2fa/setup", headers=auth_headers(init))
        assert r.status_code == 200, r.text
    finally:
        await fake.aclose()
        redis_client.override_for_tests(None)


# ── §15.8 — pre-flight check on the legacy-DealStatus drop migration ──


def test_15_8_legacy_dealstatus_migration_blocks_on_legacy_rows():
    """The pre-flight check in
    ``alembic/versions/411cbe508b97_drop_legacy_dealstatus_values`` must
    raise a helpful ``RuntimeError`` when ``count(*)`` of legacy rows
    is > 0. We don't actually run alembic here — we drive ``upgrade()``
    with a hand-rolled ``op.get_bind`` mock so the test stays a pure
    unit test against the migration's pre-flight logic.
    """
    import importlib.util
    import pathlib

    mig_path = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "alembic"
        / "versions"
        / "411cbe508b97_drop_legacy_dealstatus_values.py"
    )
    spec = importlib.util.spec_from_file_location("mig_411cbe508b97", mig_path)
    assert spec is not None and spec.loader is not None
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    fake_conn = MagicMock()
    fake_result = MagicMock()
    fake_result.scalar_one.return_value = 3  # 3 legacy rows pretend-found
    fake_conn.execute.return_value = fake_result

    from alembic import op as op_module

    # Patch op.get_bind in the migration module's namespace to return
    # our fake conn.
    original_get_bind = op_module.get_bind
    op_module.get_bind = lambda: fake_conn  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeError) as excinfo:
            mig.upgrade()
    finally:
        op_module.get_bind = original_get_bind  # type: ignore[assignment]

    msg = str(excinfo.value)
    assert "Refusing to drop legacy DealStatus values" in msg
    assert "3 row(s)" in msg
    # Mention of all 5 legacy values so the operator sees the full set.
    for legacy in ("wait_confirm", "confirmed", "success", "failed", "arbitrage"):
        assert legacy in msg, f"Migration error message lost legacy value {legacy!r}"


def test_15_8_legacy_dealstatus_migration_passes_on_clean_db():
    """Same pre-flight, but ``count(*)`` returns 0 — the migration must
    proceed past the check (we stop it short by raising in the next
    ``op.execute`` call so this stays a unit test)."""
    import importlib.util
    import pathlib

    mig_path = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "alembic"
        / "versions"
        / "411cbe508b97_drop_legacy_dealstatus_values.py"
    )
    spec = importlib.util.spec_from_file_location("mig_411cbe508b97_clean", mig_path)
    assert spec is not None and spec.loader is not None
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    fake_conn = MagicMock()
    fake_result = MagicMock()
    fake_result.scalar_one.return_value = 0
    fake_conn.execute.return_value = fake_result

    from alembic import op as op_module

    original_get_bind = op_module.get_bind
    original_execute = op_module.execute
    op_module.get_bind = lambda: fake_conn  # type: ignore[assignment]

    sentinel = RuntimeError("stopped past pre-flight")

    def _stop(*args, **kwargs):
        raise sentinel

    op_module.execute = _stop  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeError) as excinfo:
            mig.upgrade()
    finally:
        op_module.get_bind = original_get_bind  # type: ignore[assignment]
        op_module.execute = original_execute  # type: ignore[assignment]

    assert excinfo.value is sentinel, (
        "pre-flight check fired on a clean DB; should only fire when legacy rows exist"
    )
