"""Test fixtures and environment setup.

Env vars MUST be set before importing ``backend.app.config`` because
pydantic-settings reads them at import time. So this file's top-level
statements set everything up before any test or helper imports.

Tests run against a real PostgreSQL instance — the same one production
uses. ``CREATE DATABASE garant_test`` is provisioned at session start
and ``TRUNCATE`` + reseed runs between each test for isolation.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import socket
import tempfile

import pytest
import pytest_asyncio

# ── 1. Configure the test environment ──────────────────────────────────────

_test_dir = pathlib.Path(tempfile.mkdtemp(prefix="garant-pytest-"))
_media_root = _test_dir / "media"
_media_root.mkdir(exist_ok=True)

_PG_HOST = os.environ.get("POSTGRES_HOST", "localhost")
_PG_PORT = os.environ.get("POSTGRES_PORT", "5432")
_PG_USER = os.environ.get("POSTGRES_USER", "garant")
_PG_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "garant")
_PG_ADMIN_DB = os.environ.get("POSTGRES_ADMIN_DB", "postgres")
_TEST_DB_NAME = os.environ.get("POSTGRES_TEST_DB", "garant_test")

os.environ["BOT_TOKEN"] = "1234567:test-bot-token-for-pytest-do-not-use-in-prod"
os.environ["CRYPTOBOT_TOKEN"] = "test-cryptobot-token-for-pytest"
os.environ["DATABASE_URL"] = (
    f"postgresql+asyncpg://{_PG_USER}:{_PG_PASSWORD}@{_PG_HOST}:{_PG_PORT}/{_TEST_DB_NAME}"
)
os.environ["RUN_BOT"] = "false"
os.environ["INACTIVITY_SWEEP_SECONDS"] = "0"
os.environ["PIN_JWT_SECRET"] = "test-pin-secret-fixed-value-do-not-use-in-prod"
os.environ["MEDIA_ROOT"] = str(_media_root)
os.environ["ALLOW_UNSIGNED_INIT_DATA"] = "false"
# Admin-side TOTP gate: pick a sentinel that the test helpers know
# about so tests can hit 2FA-gated endpoints without going through the
# full enrolment flow. The real TOTP-rejection tests in
# ``test_admin_misc.py`` continue to exercise the production path —
# they don't send this header, they enrol a fresh secret.
#
# Guard against an accidental ``pytest`` invocation against a deployed
# environment: the bypass sentinel must never reach a process whose
# ``ENVIRONMENT`` is production/staging.
_env_value = os.environ.get("ENVIRONMENT", "test").lower()
if _env_value in ("production", "staging"):
    raise RuntimeError(
        f"Refusing to run tests with ENVIRONMENT='{_env_value}'; "
        "ADMIN_TOTP_BYPASS is a test-only escape hatch and must never be "
        "configured against a production/staging deployment."
    )
os.environ.setdefault("ADMIN_TOTP_BYPASS", "test-totp-bypass-do-not-use-in-prod")


# ── 2. Provision the test database (once per session) ─────────────────────


async def _recreate_test_db() -> None:
    """Drop + create the dedicated test database via the admin connection.

    ``WITH (FORCE)`` evicts any straggling connections from a previous
    pytest run so DROP doesn't hang. Requires PostgreSQL 13+.
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
        await conn.execute(f'DROP DATABASE IF EXISTS "{_TEST_DB_NAME}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{_TEST_DB_NAME}"')
    finally:
        await conn.close()


def _alembic_upgrade_head() -> None:
    """Run ``alembic upgrade head`` against the freshly-created test DB."""
    from alembic.config import Config

    from alembic import command

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.upgrade(cfg, "head")


asyncio.run(_recreate_test_db())
_alembic_upgrade_head()


# ── 3. Stub the Telegram-DM fan-out ────────────────────────────────────────
# ``notifier.push`` does ``asyncio.create_task(_safe_send_dm(...))`` which
# would otherwise try to hit the real Telegram API with a fake bot token,
# producing flaky stderr warnings and "Task was destroyed but it is pending"
# noise. Monkey-patching at module level (before any router imports it)
# keeps tests quiet and deterministic.

import backend.app.notifier as _notifier  # noqa: E402


async def _noop_dm(*_args, **_kwargs):
    return None


_notifier._safe_send_dm = _noop_dm  # type: ignore[assignment]


# ── 4. Per-test fresh data ────────────────────────────────────────────────


_TABLES_TO_TRUNCATE: tuple[str, ...] = (
    "reviews",
    "deal_messages",
    "deals",
    "wallet_withdrawals",
    "wallet_deposits",
    "user_balances",
    "invoices",
    "media",
    "notifications",
    "account_transfer_codes",
    "service_comments",
    "services",
    "forums",
    "users",
    "app_settings",
    "currencies",
    "categories",
)


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

    from backend.app.db import async_session, engine
    from backend.app.rate_limit import reset_state_for_tests
    from backend.app.seed import run_seed

    await engine.dispose()

    table_list = ", ".join(_TABLES_TO_TRUNCATE)
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
    except asyncio.TimeoutError:
        task.cancel()


# ── 7. Quiet noisy 3rd-party loggers ───────────────────────────────────────


@pytest.fixture(autouse=True)
def _quiet_logs(caplog):
    import logging

    logging.getLogger("aiogram").setLevel(logging.CRITICAL)
    logging.getLogger("backend.app.notifier").setLevel(logging.CRITICAL)
    logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)
    yield
