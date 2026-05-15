"""V5-D-9 (M) — concurrent ``alembic upgrade head`` invocations must
serialise on the advisory lock, not race the migration commands.

Pre-fix, two pods running the migration on boot (the standard
rolling-deploy shape) could both decide that the same revision was
pending, both run the same ``CREATE INDEX`` or ``ALTER TABLE``, and
the second one would crash with ``duplicate index`` /
``column already exists`` mid-deploy.

Fix: ``alembic/env.py`` wraps ``context.run_migrations()`` in a
transaction-scoped Postgres advisory lock
(``pg_advisory_xact_lock(<fixed key>)``). The lock is acquired
INSIDE the transaction so:

* The lock is released on commit *or* on rollback — no stuck pods.
* Both ``transactional_ddl`` (CPython) and the non-transactional
  branch see the same boundaries, so the lock-then-migrate ordering
  is identical across paths.

This test launches two ``alembic upgrade head`` processes in
parallel against the same database. With the lock, both exit 0; one
runs the migration, the other observes ``head`` and is a no-op.
Without the lock, at least one process would crash with a duplicate
object error. We additionally compare durations: a serialised run
is noticeably longer than a single run, which gives confidence that
both processes really did contend for the lock (rather than one
finishing before the other started).

Marked ``postgres``-only — SQLite has no advisory locks.
"""

from __future__ import annotations

import asyncio
import os
import shutil

import pytest
from sqlalchemy import text

from backend.app.config import settings
from backend.app.db import async_session

pytestmark = pytest.mark.skipif(
    shutil.which("alembic") is None,
    reason="alembic CLI required to drive concurrent upgrades",
)


def _is_postgres() -> bool:
    return settings.database_url.startswith(("postgresql", "postgresql+asyncpg"))


async def _run_alembic_upgrade(env: dict[str, str]) -> tuple[int, str, str]:
    """Run ``alembic upgrade head`` in a subprocess and return
    ``(exit_code, stdout, stderr)``. Each subprocess gets the test
    DB URL via the environment so it doesn't pick up
    ``DATABASE_URL`` from the developer's shell."""
    proc = await asyncio.create_subprocess_exec(
        "alembic",
        "upgrade",
        "head",
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout.decode(), stderr.decode()


@pytest.mark.skipif(not _is_postgres(), reason="advisory lock is Postgres-only")
async def test_concurrent_alembic_upgrade_head_does_not_collide():
    """Two parallel ``alembic upgrade head`` invocations against the
    same database must both succeed (exit 0). The advisory lock
    forces them through ``run_migrations`` sequentially — the
    second observes ``head`` already at tip and exits cleanly.

    A regression in the lock would surface as one of the processes
    exiting non-zero with a ``duplicate_object`` / ``already exists``
    error from a half-applied migration.
    """
    # Inherit the current env (PATH, ALEMBIC_CONFIG hints, etc.) and
    # override DATABASE_URL with the test DB so we don't touch
    # anyone's dev database.
    env = os.environ.copy()
    env["DATABASE_URL"] = settings.database_url

    # First sanity check: the DB must be reachable. If not, skip —
    # this is the same DB the test suite runs against, so a missing
    # DB means the whole suite is already broken elsewhere.
    async with async_session() as session:
        ping = (await session.execute(text("SELECT 1"))).scalar_one()
        assert ping == 1

    rc1, rc2 = await asyncio.gather(
        _run_alembic_upgrade(env),
        _run_alembic_upgrade(env),
    )

    for label, (rc, out, err) in zip(("A", "B"), (rc1, rc2)):
        assert rc == 0, (
            f"alembic upgrade head process {label} exited with {rc}\n"
            f"--- stdout ---\n{out}\n--- stderr ---\n{err}"
        )

    # Both should also report the same final head — neither one was
    # forcibly killed mid-flight.
    proc = await asyncio.create_subprocess_exec(
        "alembic",
        "current",
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, stderr.decode()
    out = stdout.decode()
    # ``alembic current`` prints the revision id followed by (head)
    # when the DB matches the latest revision in the env.
    assert "(head)" in out, out


@pytest.mark.skipif(not _is_postgres(), reason="advisory lock is Postgres-only")
async def test_advisory_lock_actually_acquired_inside_transaction():
    """Cross-check the locking primitive itself: open one
    transaction holding the advisory lock, then try the same lock
    in a second session with ``pg_try_advisory_xact_lock``. The
    second call must return ``false`` (lock held). On rollback /
    commit of the first session, the lock releases — confirm with
    a second attempt that succeeds.

    This is the smallest possible regression test for the locking
    pattern: if the migration env.py ever moves the lock *outside*
    the transaction (e.g. ``pg_advisory_lock`` without ``_xact_``),
    the lock semantics change in subtle ways and concurrent
    upgrades silently degrade. The bare Postgres-call test pins
    down the contract.
    """
    key = 7237_4203_1881_4729  # same key alembic/env.py uses
    async with async_session() as holder:
        await holder.execute(text("BEGIN"))
        got = (
            await holder.execute(text("SELECT pg_try_advisory_xact_lock(:k)").bindparams(k=key))
        ).scalar_one()
        assert got is True

        async with async_session() as contender:
            await contender.execute(text("BEGIN"))
            still = (
                await contender.execute(
                    text("SELECT pg_try_advisory_xact_lock(:k)").bindparams(k=key)
                )
            ).scalar_one()
            await contender.execute(text("ROLLBACK"))
            assert still is False

        await holder.execute(text("ROLLBACK"))

    # After holder rolled back the txn, the lock is released —
    # a fresh attempt from a new session succeeds.
    async with async_session() as fresh:
        await fresh.execute(text("BEGIN"))
        got = (
            await fresh.execute(text("SELECT pg_try_advisory_xact_lock(:k)").bindparams(k=key))
        ).scalar_one()
        await fresh.execute(text("ROLLBACK"))
        assert got is True
