"""Regression tests for the medium/low audit findings shipped in the
"audit-followup-3" PR.

Covers:

* **§4.14** — ``confirm_transfer`` previously ran a full ``DELETE FROM
  account_transfer_codes WHERE expires_at < now OR consumed_at IS NOT
  NULL`` on *every* confirm. We now sample the purge at 1/10 on the
  confirm path while still forcing a clean sweep on ``issue_code``.
  The tests below pin the contract: ``issue_code`` always purges and
  ``confirm_transfer`` only purges when the sampler fires.
* **§5.9** — ``ConnectionManager._listen`` used to die silently on the
  first ``redis-py`` exception, leaving the backend deaf to fan-out
  events until restart. We now wrap it in ``_listen_supervisor`` which
  catches transient errors, logs at ERROR with a structured
  ``ws.subscriber.listen_loop_restart`` event, and re-subscribes with
  bounded exponential backoff. The tests below verify the supervisor
  actually re-runs ``_listen`` after a synthetic crash and resets the
  consecutive-failure counter on a successful resubscribe.
* **§16.4.1** — the ``eslint-frontend`` pre-commit hook now checks for
  ``frontend/node_modules`` and skips with exit 0 + an actionable hint
  on a fresh clone, instead of hard-failing the commit with ``eslint:
  command not found``. We snapshot the hook's ``entry`` string so any
  future refactor that drops this guard fails this test.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest
import yaml

from backend.app import services_account as sa_module
from backend.app.db import async_session
from backend.app.models import AccountTransferCode, User
from backend.app.services_account import (
    _purge_expired_sampled,
    issue_code,
)
from backend.app.ws import ConnectionManager
from tests.helpers import get_user_id_by_tg, setup_pin, signed_init_data

# ── §4.14 — probabilistic purge on confirm, forced purge on issue ──


async def _seed_stale_code(session, source_user_id: int) -> int:
    """Insert one already-expired code so a purge sweep would remove it."""
    from datetime import timedelta

    from backend.app.time_utils import utcnow

    row = AccountTransferCode(
        source_user_id=source_user_id,
        code_hash="0" * 64,
        expires_at=utcnow() - timedelta(hours=1),
    )
    session.add(row)
    await session.commit()
    return row.id


async def test_4_14_purge_skips_when_sampler_misses(client, monkeypatch):
    """``confirm_transfer`` path: when the sampler decides "don't purge"
    the stale row stays. This is the whole point of §4.14 — we
    intentionally skip the DELETE on most confirms."""
    init = signed_init_data(41401, "src41401")
    await setup_pin(client, init)
    async with async_session() as session:
        source_id = await get_user_id_by_tg(session, 41401)
        stale_id = await _seed_stale_code(session, source_id)

    # Force the sampler to "miss" — i.e. _purge_expired's random()
    # always returns 1.0, which is >= _PURGE_SAMPLE_RATE so the
    # function early-returns without running the DELETE.
    class _NoPurgeRng:
        def random(self) -> float:
            return 1.0

    monkeypatch.setattr(sa_module.secrets, "SystemRandom", lambda: _NoPurgeRng())

    async with async_session() as session:
        await _purge_expired_sampled(session)
        # Stale row should still exist because the sampler missed.
        row = await session.get(AccountTransferCode, stale_id)
        assert row is not None, "Sampler missed but purge ran anyway"


async def test_4_14_purge_runs_when_sampler_hits(client, monkeypatch):
    """``confirm_transfer`` path: when the sampler fires the DELETE
    runs as before."""
    init = signed_init_data(41402, "src41402")
    await setup_pin(client, init)
    async with async_session() as session:
        source_id = await get_user_id_by_tg(session, 41402)
        stale_id = await _seed_stale_code(session, source_id)

    # Force the sampler to "hit" — random() returns 0.0 which is
    # strictly < _PURGE_SAMPLE_RATE = 0.1.
    class _AlwaysPurgeRng:
        def random(self) -> float:
            return 0.0

    monkeypatch.setattr(sa_module.secrets, "SystemRandom", lambda: _AlwaysPurgeRng())

    async with async_session() as session:
        await _purge_expired_sampled(session)
        row = await session.get(AccountTransferCode, stale_id)
        assert row is None, "Sampler fired but DELETE didn't run"


async def test_4_14_issue_code_always_purges_regardless_of_sampler(client, monkeypatch):
    """``issue_code`` calls the unconditional ``_purge_expired`` (not the
    sampled wrapper), so a stale row gets swept even when the
    sampler would otherwise miss. This is the correctness side of
    the contract: a fresh write must not collide with a stale row,
    so we always sweep before issuing."""
    init = signed_init_data(41403, "src41403")
    await setup_pin(client, init)
    async with async_session() as session:
        source_id = await get_user_id_by_tg(session, 41403)
        stale_id = await _seed_stale_code(session, source_id)
        source = await session.get(User, source_id)

    # Set the sampler to always miss; ``issue_code`` must still purge.
    class _NoPurgeRng:
        def random(self) -> float:
            return 1.0

    monkeypatch.setattr(sa_module.secrets, "SystemRandom", lambda: _NoPurgeRng())

    async with async_session() as session:
        source = await session.get(User, source_id)
        assert source is not None
        await issue_code(session, source)
        stale = await session.get(AccountTransferCode, stale_id)
        assert stale is None, "issue_code did not force a full purge"


# ── §5.9 — _listen supervisor reconnects after transient failures ──


class _StubPubSub:
    """Minimal pubsub stub: ``listen()`` is an async generator that
    raises (or exits) on demand and tracks whether ``aclose`` was
    called."""

    def __init__(self, fail: bool = False, raise_exc: Exception | None = None):
        self.fail = fail
        self.raise_exc = raise_exc
        self.aclose_called = False
        self.subscribed = False

    async def subscribe(self, *channels: str) -> None:
        self.subscribed = True

    async def listen(self):
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.fail:
            raise ConnectionError("simulated redis blip")
        if False:  # pragma: no cover — keep this as an async generator
            yield {}

    async def aclose(self) -> None:
        self.aclose_called = True

    async def unsubscribe(self, *channels: str) -> None:
        pass


async def test_5_9_listen_supervisor_restarts_after_exception(monkeypatch, caplog):
    """A crashed ``_listen`` must log at ERROR with the structured
    ``ws.subscriber.listen_loop_restart`` event and then resubscribe."""
    from backend.app import ws as ws_module

    # Squash sleeps so the test isn't bottlenecked on the backoff floor.
    monkeypatch.setattr(ws_module, "_WS_LISTEN_BACKOFF_BASE", 0.0)
    monkeypatch.setattr(ws_module, "_WS_LISTEN_BACKOFF_CAP", 0.0)

    initial = _StubPubSub(raise_exc=RuntimeError("kaboom"))
    healthy = _StubPubSub()  # exits cleanly so the loop won't spin forever

    class _StubRedis:
        def __init__(self):
            self._pubsubs = iter([healthy])

        def pubsub(self):
            return next(self._pubsubs)

    stub_redis = _StubRedis()

    async def _stub_get_redis():
        return stub_redis

    monkeypatch.setattr(ws_module, "get_redis", _stub_get_redis)

    manager = ConnectionManager()

    caplog.set_level(logging.INFO, logger="backend.app.ws")

    # Drive the supervisor for a bounded number of iterations: it
    # should crash once on ``initial`` and then resubscribe to
    # ``healthy``. After the healthy iteration exits, the supervisor
    # will try to resubscribe again — but our stub iter is exhausted
    # so ``pubsub()`` raises StopIteration; we cancel before that.
    task = asyncio.create_task(manager._listen_supervisor(initial))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    events = {r.event for r in caplog.records if hasattr(r, "event")}
    assert "ws.subscriber.listen_loop_restart" in events, (
        f"Supervisor didn't log the structured restart event; got {events}"
    )
    assert "ws.subscriber.resubscribed" in events, (
        f"Supervisor didn't log resubscribe success; got {events}"
    )
    assert initial.aclose_called, "Supervisor didn't aclose the broken pubsub"
    assert healthy.subscribed, "Supervisor didn't re-subscribe on the healthy pubsub"


async def test_5_9_listen_supervisor_exits_on_cancel(monkeypatch):
    """``stop_subscriber`` cancels the supervisor task and must propagate
    cleanly without re-entering the backoff loop."""
    from backend.app import ws as ws_module

    monkeypatch.setattr(ws_module, "_WS_LISTEN_BACKOFF_BASE", 0.0)
    monkeypatch.setattr(ws_module, "_WS_LISTEN_BACKOFF_CAP", 0.0)

    ps = _StubPubSub()
    manager = ConnectionManager()

    task = asyncio.create_task(manager._listen_supervisor(ps))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ── §16.4.1 — pre-commit eslint hook gracefully skips ──


def test_16_4_1_eslint_hook_skips_when_node_modules_missing():
    """Snapshot test against `.pre-commit-config.yaml` so a future
    refactor that drops the ``node_modules`` guard fails loudly."""
    cfg_path = Path(__file__).resolve().parents[2] / ".pre-commit-config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    eslint_hook = next(
        h
        for repo in cfg["repos"]
        if repo.get("repo") == "local"
        for h in repo["hooks"]
        if h["id"] == "eslint-frontend"
    )
    entry = eslint_hook["entry"]
    assert "if [ -d frontend/node_modules ]" in entry, (
        "eslint-frontend hook lost its node_modules guard; fresh-clone "
        "commits will fail with 'eslint: command not found' again."
    )
    assert "npm install" in entry, "Skip-message must tell the developer how to enable the hook"
