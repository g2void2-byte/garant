"""WS hardening tests for review-report Appendix B items B.2 + B.3.

* **B.2 — connection age cap by ``auth_date``.** Verifies
  :meth:`ConnectionManager._evict_expired_once` closes sockets whose
  ``initData.auth_date`` has aged past ``WS_MAX_AGE_SECONDS`` and
  leaves fresh ones alone.
* **B.3 — bounded outgoing queue / drop-oldest.** Verifies a slow
  consumer can't grow the per-socket send buffer past
  ``WS_SEND_QUEUE_SIZE``; oldest events are dropped instead.

The B.2 tests use the real WebSocket transport via the ``ws_server``
fixture so we can assert the 4002 close code the way a browser
client would observe it. The B.3 tests drive ``ConnectionManager``
directly with a mock ``send_text`` we can gate open / closed at will,
because reproducing TCP back-pressure deterministically against a
real socket is platform-dependent.
"""

from __future__ import annotations

import asyncio
import json

import pytest
import websockets

from backend.app.ws import ConnectionManager
from tests.helpers import signed_init_data


async def _connect_and_auth(ws_server: int, init_data: str):
    """Open a socket and complete the first-message handshake."""
    url = f"ws://127.0.0.1:{ws_server}/ws/notifications"
    ws = await websockets.connect(url, open_timeout=5)
    await ws.send(json.dumps({"type": "auth", "init_data": init_data}))
    ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
    assert ack == {"type": "auth", "ok": True}, ack
    return ws


# ───────────────────── B.2: age-cap reaper ──────────────────────────────


async def test_age_cap_closes_socket_when_auth_date_too_old(ws_server, monkeypatch):
    """B.2 — a socket whose ``auth_date`` has aged past the cap is
    closed by the reaper with code 4002 ("Auth expired").

    We force ``WS_MAX_AGE_SECONDS`` negative so that *any* socket is
    instantly "expired" — the helper's ``signed_init_data`` stamps
    ``auth_date = int(time.time())`` which the reaper will reject
    against ``cutoff = now - (-2) > auth_date``.
    """
    from backend.app.ws import manager

    monkeypatch.setattr("backend.app.ws.WS_MAX_AGE_SECONDS", -2)

    init_data = signed_init_data(7101, "stale7101")
    ws = await _connect_and_auth(ws_server, init_data)
    try:
        # Give the endpoint a moment to register the socket in the
        # manager's ``_states`` map before we sweep.
        for _ in range(20):
            if any(s.user_id for s in manager._states.values()):
                break
            await asyncio.sleep(0.05)

        evicted = await manager._evict_expired_once()
        assert evicted >= 1, "reaper did not evict the stale socket"

        try:
            await asyncio.wait_for(ws.recv(), timeout=3.0)
            raise AssertionError("expected close, got a frame")
        except websockets.exceptions.ConnectionClosed as exc:
            assert exc.code == 4002, (exc.code, exc.reason)
            assert "expired" in str(exc.reason).lower()
    finally:
        try:
            await ws.close()
        except Exception:
            pass


async def test_age_cap_skips_fresh_socket(ws_server, monkeypatch):
    """B.2 — sockets younger than ``WS_MAX_AGE_SECONDS`` survive a sweep."""
    from backend.app.ws import manager

    # 1 hour cap; ``auth_date`` will be "now" → cutoff = now-3600 < now.
    monkeypatch.setattr("backend.app.ws.WS_MAX_AGE_SECONDS", 3600)

    init_data = signed_init_data(7102, "fresh7102")
    ws = await _connect_and_auth(ws_server, init_data)
    try:
        for _ in range(20):
            if any(s.user_id for s in manager._states.values()):
                break
            await asyncio.sleep(0.05)

        evicted = await manager._evict_expired_once()
        assert evicted == 0, "reaper evicted a fresh socket"

        # Socket should still be alive.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(ws.recv(), timeout=0.3)
    finally:
        try:
            await ws.close()
        except Exception:
            pass


async def test_age_cap_skips_socket_without_auth_date():
    """B.2 — sockets registered with ``auth_date_epoch=None`` are not
    evicted. Older clients / unsigned-dev-data don't get spuriously
    closed.
    """

    class _FakeWS:
        def __init__(self) -> None:
            self.closed_with: tuple[int, str] | None = None

        async def send_text(self, _text: str) -> None:
            return None

        async def close(self, code: int = 1000, reason: str = "") -> None:
            self.closed_with = (code, reason)

    mgr = ConnectionManager()
    ws = _FakeWS()
    await mgr.connect(user_id=999, websocket=ws, auth_date_epoch=None)  # type: ignore[arg-type]
    try:
        evicted = await mgr._evict_expired_once()
        assert evicted == 0
        assert ws.closed_with is None
    finally:
        mgr.disconnect(999, ws)  # type: ignore[arg-type]


# ───────────────────── B.3: bounded queue / drop-oldest ─────────────────


class _GatedWebSocket:
    """Mock WebSocket whose ``send_text`` blocks until ``gate`` is set.

    Lets the test stall the writer task deterministically so the
    bounded outgoing queue overflows and we can assert the drop-oldest
    counter advanced.
    """

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.sent: list[str] = []
        self.closed_with: tuple[int, str] | None = None

    async def send_text(self, text: str) -> None:
        await self.gate.wait()
        self.sent.append(text)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed_with = (code, reason)


async def test_send_queue_drops_oldest_on_overflow(monkeypatch):
    """B.3 — when the writer is stalled and the producer keeps pushing,
    the oldest enqueued frames are dropped, ``state.dropped`` advances,
    and the queue size never exceeds ``WS_SEND_QUEUE_SIZE``.
    """
    monkeypatch.setattr("backend.app.ws.WS_SEND_QUEUE_SIZE", 3)

    mgr = ConnectionManager()
    fake = _GatedWebSocket()
    await mgr.connect(user_id=1, websocket=fake, auth_date_epoch=None)  # type: ignore[arg-type]
    try:
        # Give the writer task a tick to start and pop the first item
        # off the queue (it'll block in ``send_text`` waiting on
        # ``fake.gate``).
        for i in range(10):
            await mgr._send_local(1, {"i": i})
            # tiny yield so the writer gets a turn to popleft the
            # first one before the queue starts overflowing
            if i == 0:
                await asyncio.sleep(0.01)

        await asyncio.sleep(0.05)

        state = mgr._states[id(fake)]
        assert state.queue.maxlen == 3
        assert len(state.queue) <= 3, f"queue grew past maxlen: {len(state.queue)} > 3"
        assert state.dropped > 0, f"expected drops with stalled writer; dropped={state.dropped}"

        # The 3 items still in the queue must be the *newest* ones —
        # ``deque(maxlen=N)`` evicts the oldest on append.
        remaining = [json.loads(p)["i"] for p in state.queue]
        assert remaining == sorted(remaining), remaining
        assert max(remaining) == 9, remaining

        # Now release the writer and let it drain; assert the *first*
        # message (popped before the gate held) plus the 3 surviving
        # tail messages arrived in order.
        fake.gate.set()
        for _ in range(50):
            if len(fake.sent) >= 1 + len(remaining):
                break
            await asyncio.sleep(0.02)
        delivered = [json.loads(t)["i"] for t in fake.sent]
        assert delivered[0] == 0, delivered  # popped before overflow
        assert delivered[1:] == remaining, (delivered, remaining)
    finally:
        mgr.disconnect(1, fake)  # type: ignore[arg-type]


async def test_send_queue_normal_flow_delivers_in_order():
    """B.3 sanity — with a responsive consumer the writer pumps every
    message through in FIFO order and ``dropped`` stays at 0.
    """
    mgr = ConnectionManager()
    fake = _GatedWebSocket()
    fake.gate.set()  # consumer is awake from the start
    await mgr.connect(user_id=2, websocket=fake, auth_date_epoch=None)  # type: ignore[arg-type]
    try:
        for i in range(20):
            await mgr._send_local(2, {"i": i})

        # Drain. The writer doesn't yield deterministically between
        # ``send_text`` calls, so loop until we've seen all 20.
        for _ in range(100):
            if len(fake.sent) >= 20:
                break
            await asyncio.sleep(0.02)

        delivered = [json.loads(t)["i"] for t in fake.sent]
        assert delivered == list(range(20)), delivered
        state = mgr._states[id(fake)]
        assert state.dropped == 0, state.dropped
    finally:
        mgr.disconnect(2, fake)  # type: ignore[arg-type]


async def test_disconnect_cancels_writer():
    """B.3 — :meth:`ConnectionManager.disconnect` cancels the writer
    task so a held queue doesn't keep the loop alive after the socket
    is gone.
    """
    mgr = ConnectionManager()
    fake = _GatedWebSocket()
    await mgr.connect(user_id=3, websocket=fake, auth_date_epoch=None)  # type: ignore[arg-type]

    state = mgr._states[id(fake)]
    writer = state.writer_task
    assert writer is not None

    mgr.disconnect(3, fake)  # type: ignore[arg-type]

    # Writer task must be cancelled / completed quickly after disconnect.
    for _ in range(50):
        if writer.done():
            break
        await asyncio.sleep(0.02)
    assert writer.done(), "writer task did not exit after disconnect"
