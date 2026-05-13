"""Test fixtures and environment setup.

Env vars MUST be set before importing ``backend.app.config`` because
pydantic-settings reads them at import time. So this file's top-level
statements set everything up before any test or helper imports.
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
_test_db = _test_dir / "test.db"
_media_root = _test_dir / "media"
_media_root.mkdir(exist_ok=True)

os.environ["BOT_TOKEN"] = "1234567:test-bot-token-for-pytest-do-not-use-in-prod"
os.environ["CRYPTOBOT_TOKEN"] = "test-cryptobot-token-for-pytest"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_test_db}"
os.environ["RUN_BOT"] = "false"
os.environ["INACTIVITY_SWEEP_SECONDS"] = "0"
os.environ["PIN_JWT_SECRET"] = "test-pin-secret-fixed-value-do-not-use-in-prod"
os.environ["MEDIA_ROOT"] = str(_media_root)
os.environ["ALLOW_UNSIGNED_INIT_DATA"] = "false"


# ── 2. Stub the Telegram-DM fan-out ────────────────────────────────────────
# ``notifier.push`` does ``asyncio.create_task(_safe_send_dm(...))`` which
# would otherwise try to hit the real Telegram API with a fake bot token,
# producing flaky stderr warnings and "Task was destroyed but it is pending"
# noise. Monkey-patching at module level (before any router imports it)
# keeps tests quiet and deterministic.

import backend.app.notifier as _notifier  # noqa: E402


async def _noop_dm(*_args, **_kwargs):
    return None


_notifier._safe_send_dm = _noop_dm  # type: ignore[assignment]


# ── 3. Per-test fresh database ─────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def reset_db():
    """Drop and recreate all tables, then run seed (currencies, categories, settings).

    Also wipes the in-process rate-limit buckets so a test doesn't see
    leftover hits from an earlier one.
    """
    from backend.app.db import Base, async_session, engine
    from backend.app.rate_limit import reset_state_for_tests
    from backend.app.seed import run_seed

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        await run_seed(session)

    reset_state_for_tests()

    yield


# ── 4. HTTP client over ASGI transport ─────────────────────────────────────


@pytest_asyncio.fixture
async def client():
    from httpx import ASGITransport, AsyncClient

    from backend.app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


# ── 5. Uvicorn server for WebSocket tests ──────────────────────────────────
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


# ── 6. Quiet noisy 3rd-party loggers ───────────────────────────────────────


@pytest.fixture(autouse=True)
def _quiet_logs(caplog):
    import logging

    logging.getLogger("aiogram").setLevel(logging.CRITICAL)
    logging.getLogger("backend.app.notifier").setLevel(logging.CRITICAL)
    logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)
    yield
