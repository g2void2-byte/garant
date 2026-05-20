"""Test fixtures and environment setup.

Static env vars are owned by ``pytest-env`` (configured in
``pyproject.toml``'s ``[tool.pytest.ini_options].env`` block); they
are set BEFORE pytest imports this module, so the legacy module-top
``os.environ[...]`` chain is gone. This file only owns the
*dynamic* env vars that can't be expressed as a static literal:

* a random per-pytest-invocation ``ADMIN_TOTP_BYPASS`` sentinel
  (V12-H1 — the previous repo-checked-in constant made every reader
  of the repo a holder of the bypass secret; the random value never
  escapes the test process and the helpers in ``tests/helpers.py``
  read the live env var so call sites stay unchanged),
* ``DATABASE_URL`` composed from the ``POSTGRES_*`` discrete env
  vars (so CI can override host/user/password via standard
  Postgres env without rewriting the URL),
* ``MEDIA_ROOT`` pointing at an ephemeral per-session tempdir
  (V12-M9 — auto-cleanup via ``atexit`` so long-lived runners don't
  accumulate stray ``/tmp/garant-pytest-*`` trees).

Tests run against a real PostgreSQL instance — the same one production
uses. ``CREATE DATABASE garant_test`` is provisioned at session start
and ``TRUNCATE`` + reseed runs between each test for isolation.
"""

from __future__ import annotations

import asyncio
import atexit
import os
import pathlib
import secrets
import shutil
import socket
import sys
import tempfile

import pytest
import pytest_asyncio

# ── 1. Configure the test environment ──────────────────────────────────────

# V12-L5 — assert that ``pytest-env`` has run and that ``backend``
# config has *not* been imported yet. The order matters: pydantic
# settings read env vars at ``Settings()`` instantiation, which
# happens at the top of ``backend.app.config``. If something on the
# import chain pulls in the config module before this conftest
# finishes the dynamic-env setup below, the random
# ``ADMIN_TOTP_BYPASS`` / composed ``DATABASE_URL`` would be missed
# and the test process would silently bind to whatever ``DATABASE_URL``
# the shell had set (== the dev DB on a laptop). Failing fast here
# turns that silent footgun into an actionable RuntimeError.
if "backend.app.config" in sys.modules:
    raise RuntimeError(
        "conftest.py: backend.app.config was imported before test env "
        "setup ran. pytest-env should populate static env vars from "
        "pyproject.toml before any test module is imported, and "
        "conftest.py must finish writing the dynamic ones before "
        "anything touches backend.app. Look for an ``import backend`` "
        "near the top of conftest.py, a test helper, or a plugin."
    )

# V12-M9 — use ``TemporaryDirectory`` semantics (auto-cleanup via
# ``atexit``) rather than a bare ``mkdtemp`` that the OS never removes.
# Pre-fix every pytest run left a stray ``/tmp/garant-pytest-*`` tree
# behind containing avatar/banner/attachment uploads from that session,
# which accumulated across runs on long-lived CI runners and developer
# laptops. ``shutil.rmtree(..., ignore_errors=True)`` is forgiving so a
# crashed pytest doesn't leak a file-lock complaint into the next run.
_test_dir = pathlib.Path(tempfile.mkdtemp(prefix="garant-pytest-"))
_media_root = _test_dir / "media"
_media_root.mkdir(exist_ok=True)


@atexit.register
def _cleanup_test_dir() -> None:
    shutil.rmtree(_test_dir, ignore_errors=True)


_PG_HOST = os.environ.get("POSTGRES_HOST", "localhost")
_PG_PORT = os.environ.get("POSTGRES_PORT", "5432")
_PG_USER = os.environ.get("POSTGRES_USER", "garant")
_PG_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "garant")
_PG_ADMIN_DB = os.environ.get("POSTGRES_ADMIN_DB", "postgres")
_TEST_DB_NAME = os.environ.get("POSTGRES_TEST_DB", "garant_test")

# V12-L5 — dynamic env vars only (see module docstring). Static
# defaults live in ``pyproject.toml`` under
# ``[tool.pytest.ini_options].env``. ``DATABASE_URL`` is composed
# from the discrete ``POSTGRES_*`` vars (so CI can swap host/user
# without rewriting the URL); ``MEDIA_ROOT`` points at the
# ephemeral per-session tempdir; ``ADMIN_TOTP_BYPASS`` is a fresh
# random sentinel per invocation.
os.environ["DATABASE_URL"] = (
    f"postgresql+asyncpg://{_PG_USER}:{_PG_PASSWORD}@{_PG_HOST}:{_PG_PORT}/{_TEST_DB_NAME}"
)
os.environ["MEDIA_ROOT"] = str(_media_root)

# V12-H1 — strict environment gate for the TOTP-bypass escape hatch.
# Pre-fix the guard was an *opt-out* deny-list (``in {"production",
# "staging"}``) which silently passed any other value — a typo
# (``prod``, ``Production``, trailing whitespace, missing var) reads
# as "not production" and the bypass would be installed against a
# real deploy. We now default-deny: only the two values we explicitly
# expect (``test``, ``development``) are accepted. Anything else
# (``""``, ``"prod"``, ``"Staging"``, …) refuses to install the
# bypass. ``ENVIRONMENT`` itself is set via pytest-env to ``test`` by
# default; this check guards against a shell override.
_env_value = os.environ.get("ENVIRONMENT", "test").strip().lower()
if _env_value not in ("test", "development"):
    raise RuntimeError(
        f"Refusing to run tests with ENVIRONMENT='{_env_value}'; "
        "ADMIN_TOTP_BYPASS is a test-only escape hatch and only "
        "ENVIRONMENT='test' or 'development' is accepted."
    )
# V12-H1 — pick a fresh random sentinel for every pytest invocation
# instead of the previous repo-checked-in string. The old constant
# made every reader of the repo a holder of the bypass secret — if it
# ever ended up configured on a deployed instance (env-var copy/paste,
# k8s secret churn), every 2FA-gated admin route would be open to any
# attacker who knew to send the literal in ``X-Totp-Code``. The
# random per-run value never escapes the test process; the helpers in
# ``tests/helpers.py`` read the live env var so call sites stay
# unchanged. ``setdefault`` is preserved so a caller can still pin a
# specific value via the env (handy for the rare debugging session
# where you want to reproduce a CI failure with a known token).
os.environ.setdefault("ADMIN_TOTP_BYPASS", secrets.token_urlsafe(32))


# ── 2. Provision the test database (once per session) ─────────────────────


# V12-M8 (follow-up) — serialise the *entire* test-DB bootstrap
# (DROP + CREATE + ``alembic upgrade head``) across parallel
# pytest-xdist workers, not just the DROP/CREATE pair. Pre-fix the
# lock was released as soon as ``CREATE`` returned, so worker A
# could be midway through alembic when worker B reacquired the
# admin lock and re-DROP'd the same database under A's feet.
#
# The lock key is deliberately *distinct* from the one
# ``alembic/env.py`` uses inside ``do_run_migrations``. Both keys
# live in the same Postgres-server-wide advisory-lock namespace, so
# reusing the alembic key here would have alembic block on its own
# ``pg_advisory_xact_lock`` call while *we* held the same key on the
# admin connection — a deterministic deadlock. The bootstrap key is
# the ``hashtext('garant_test_db_bootstrap')`` value (1_075_088_959)
# while alembic uses its own constant; the comment in
# ``alembic/env.py`` documents the alembic side.
_TEST_DB_BOOTSTRAP_LOCK = 1_075_088_959


def _alembic_upgrade_head() -> None:
    """Run ``alembic upgrade head`` against the freshly-created test DB."""
    from alembic.config import Config

    from alembic import command

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.upgrade(cfg, "head")


async def _bootstrap_test_db() -> None:
    """Drop + create + migrate the dedicated test database.

    All three phases run under a single session-level advisory lock
    held on the admin connection so concurrent xdist workers serialise
    here, not just on the DROP/CREATE pair. ``WITH (FORCE)`` evicts any
    straggling connections from a previous pytest run so DROP doesn't
    hang (requires PostgreSQL 13+).
    """
    import asyncpg  # local import: only needed during test setup.

    conn = await asyncpg.connect(
        host=_PG_HOST,
        port=int(_PG_PORT),
        user=_PG_USER,
        password=_PG_PASSWORD,
        database=_PG_ADMIN_DB,
    )
    try:
        await conn.execute(f"SELECT pg_advisory_lock({_TEST_DB_BOOTSTRAP_LOCK})")
        try:
            await conn.execute(f'DROP DATABASE IF EXISTS "{_TEST_DB_NAME}" WITH (FORCE)')
            await conn.execute(f'CREATE DATABASE "{_TEST_DB_NAME}"')
            # Migrate while we still hold the lock: alembic's own
            # ``pg_advisory_xact_lock`` uses a different key (see
            # ``alembic/env.py``) and won't contend with this one, but
            # another xdist worker waiting on the bootstrap lock will
            # block here until migrations complete. ``to_thread`` is
            # required because ``command.upgrade`` ultimately calls
            # ``asyncio.run`` itself (via ``run_migrations_online`` in
            # ``alembic/env.py``) and nested ``asyncio.run`` invocations
            # raise; off-loading to a worker thread gives alembic a
            # fresh event loop.
            await asyncio.to_thread(_alembic_upgrade_head)
        finally:
            # Best-effort release; the connection is about to close
            # which would release the session lock anyway, but an
            # explicit unlock keeps the lock-table tidy in case the
            # admin connection is recycled by the driver.
            await conn.execute(f"SELECT pg_advisory_unlock({_TEST_DB_BOOTSTRAP_LOCK})")
    finally:
        await conn.close()


asyncio.run(_bootstrap_test_db())


# ── 3. Stub the Telegram-DM fan-out ────────────────────────────────────────
# ``notifier.push`` does ``asyncio.create_task(_safe_send_dm(...))`` which
# would otherwise try to hit the real Telegram API with a fake bot token,
# producing flaky stderr warnings and "Task was destroyed but it is pending"
# noise. The stub is installed per-test via ``monkeypatch`` so pytest
# auto-reverts it after each test (V12-M7) — pre-fix the patch was
# applied at module-import time with no teardown, so a future rename
# of ``_safe_send_dm`` would silently fall back to the real call (and
# any in-test ``monkeypatch.setattr`` against the symbol would leak
# across tests).


async def _noop_dm(*_args: object, **_kwargs: object) -> None:
    return None


@pytest.fixture(autouse=True)
def _stub_telegram_dm(monkeypatch):
    """Replace ``notifier._safe_send_dm`` with a no-op for the test duration.

    Autouse so every test benefits without opting in; tests that need
    to assert real DM dispatch can override the fixture or
    ``monkeypatch.setattr`` to a different stub.
    """
    import backend.app.notifier as _notifier

    monkeypatch.setattr(_notifier, "_safe_send_dm", _noop_dm)


# ── 4. Per-test fresh data ────────────────────────────────────────────────


# V12-H6 — derive the truncate set from the ORM metadata at first use
# rather than maintaining a hand-edited tuple. Pre-fix every new model
# silently leaked state into subsequent tests (the table simply
# wasn't in ``_TABLES_TO_TRUNCATE``); broadcasts, treasury withdrawals
# and admin audit-log rows accumulated across the run. Introspection
# also keeps the list FK-aware automatically — ``metadata.sorted_tables``
# returns dependency order so ``CASCADE`` is a safety net rather than
# the load-bearing primitive. Cached because the metadata is static
# once ``backend.app.models`` is imported.
_truncate_targets: tuple[str, ...] | None = None


def _tables_to_truncate() -> tuple[str, ...]:
    global _truncate_targets
    if _truncate_targets is None:
        from backend.app.db import Base

        # Reverse so the children-first ordering is preferred when we
        # join the table list into a single TRUNCATE statement — Postgres
        # does the actual cascading either way, but reverse-dep order
        # is what you'd want if a future change drops ``CASCADE``.
        _truncate_targets = tuple(table.name for table in reversed(Base.metadata.sorted_tables))
    return _truncate_targets


@pytest_asyncio.fixture(autouse=True)
async def reset_db():
    """Truncate every table (FK-cascading) and re-run the idempotent seed.

    ``RESTART IDENTITY`` resets autoincrement sequences so id=1 is
    predictable across tests. Faster than drop_all/create_all because
    schema stays put.

    ``engine.dispose()`` evicts any asyncpg connections opened on a
    previous test's event loop — pytest-asyncio creates a fresh loop per
    test function, so pooled connections from the prior run would raise
    "Future attached to a different loop" RuntimeError otherwise.
    """
    from sqlalchemy import text

    from backend.app.db import get_async_session, get_engine, reset_engine_for_tests
    from backend.app.rate_limit import reset_state_for_tests
    from backend.app.seed import run_seed

    # V11-M-18 — dispose-and-rebuild rather than dispose-in-place so
    # the asyncpg pool is freshly attached to *this* test's event loop.
    # pytest-asyncio creates a per-function loop and the previous run's
    # pool, even after ``dispose``, can still leak a half-closed
    # connection into the new loop and raise "Future attached to a
    # different loop". Re-creating the engine from scratch is the
    # cheapest reliable fix.
    await reset_engine_for_tests()
    engine = get_engine()
    async_session = get_async_session()

    table_list = ", ".join(f'"{name}"' for name in _tables_to_truncate())
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE"))

    async with async_session() as session:
        await run_seed(session)

    reset_state_for_tests()

    yield


# ── 5. HTTP client over ASGI transport ─────────────────────────────────────


@pytest_asyncio.fixture
async def client():
    from httpx import ASGITransport, AsyncClient

    from backend.app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


# ── 6. Uvicorn server for WebSocket tests ──────────────────────────────────
# WebSocket testing through ASGITransport is awkward (httpx doesn't support
# it directly), so for WS-specific tests we spin up an in-process uvicorn
# bound to a random port and connect via the ``websockets`` library — the
# same way a real browser would.


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest_asyncio.fixture
async def ws_server():
    import uvicorn

    from backend.app.main import app

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())

    # Wait until the listening socket is up.
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.05)
    else:
        raise RuntimeError("uvicorn did not start within 2.5s")

    yield port

    server.should_exit = True
    try:
        await asyncio.wait_for(task, timeout=3.0)
    except TimeoutError:
        task.cancel()


# ── 7. Quiet noisy 3rd-party loggers ───────────────────────────────────────


# V12-L11 — narrow the mute to specific noisy children rather than
# blanket-CRITICAL on the whole logger tree. Pre-fix every
# ``logger.error`` (and even ``logger.warning``) emitted from
# ``aiogram`` / ``backend.app.notifier`` / ``uvicorn.error`` was
# silently swallowed by tests — including the production-relevant ones
# (notifier DB-failure paths, uvicorn lifespan crashes) that ought to
# surface as test failures whenever a regression introduces a noisy
# log. The ``aiogram.dispatcher`` and ``uvicorn.access`` children are
# the actually-noisy paths: dispatcher logs polling reconnects /
# delivery retries; access logs every fixture HTTP call at INFO. Both
# are unrelated to anything we want to fail on. Everything else (a
# fresh ``logger.error`` in ``backend.app.notifier``, an unexpected
# ``uvicorn.error`` crash log) stays at WARNING and is captured by
# ``caplog`` so individual tests can still assert on the records.
_QUIETED_LOGGERS = (
    # Polling chatter, retry / reconnect cycles. Test fixtures stub
    # ``notifier._safe_send_dm`` so no real telegram calls happen, but
    # aiogram's dispatcher still emits "got update / no handler"
    # records that have nothing to teach us.
    ("aiogram.dispatcher", "CRITICAL"),
    ("aiogram.event", "CRITICAL"),
    # Per-request access log; CI captures stderr at the runner level
    # so duplicating it under WARNING is pure noise.
    ("uvicorn.access", "CRITICAL"),
)


@pytest.fixture(autouse=True)
def _quiet_logs(caplog):
    import logging

    for name, level in _QUIETED_LOGGERS:
        logging.getLogger(name).setLevel(getattr(logging, level))
    # Keep the parents at WARNING so any *new* ``logger.error`` /
    # ``logger.warning`` in code we own surfaces immediately. ``caplog``
    # is wired by the fixture so individual tests can still assert on
    # specific log records under these names.
    for name in ("aiogram", "backend.app.notifier", "uvicorn.error"):
        logging.getLogger(name).setLevel(logging.WARNING)
    yield
