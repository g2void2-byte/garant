"""WebSocket connection manager + optional Redis fan-out (P3.5).

``ConnectionManager`` tracks user → WebSocket(s) maps locally. When
Redis is configured, ``publish`` PUBLISHes a JSON envelope on the
``ws:notifications`` channel and a background ``_listen`` task on every
backend instance pushes the message to its locally-attached sockets.
That gives horizontal-scale fan-out (multiple uvicorn workers /
multiple replicas) without each worker holding every connection.

When Redis is unavailable, ``publish`` falls back to direct local
delivery — the previous in-process behaviour. This means the test
suite, single-process deployments, and the dev loop don't need Redis
running.

Two pieces of WS hardening live here (review report Appendix B,
items B.2 + B.3):

* **Per-socket bounded outgoing queue (B.3).** Each accepted socket
  gets a ``deque`` of fixed length (``WS_SEND_QUEUE_SIZE``) and a
  dedicated writer task that drains the queue with
  ``websocket.send_text``. ``publish`` enqueues; the writer pumps. If
  the queue fills (slow consumer / TCP back-pressure /
  disconnected-but-not-closed device) the oldest message is dropped
  rather than letting the send buffer balloon and OOM the server.
* **Connection age cap by ``auth_date`` (B.2).** ``connect`` records
  the Telegram ``initData.auth_date`` epoch. A background reaper
  scans every ``settings.ws_age_check_interval_seconds`` and closes
  any socket whose ``auth_date`` is older than
  ``settings.ws_max_age_seconds`` (default 12 h). That bounds how
  long a stolen/forwarded initData can keep a live notifications
  channel alive past the ``settings.init_data_max_age_seconds``
  window the auth check itself enforces at handshake time. (V11-H-9
  — the previous docstring claimed 24 h, but ``verify_init_data``
  reuses the same configurable TTL as REST routes; in stock config
  that's 15 min, *not* 24 h.)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from .config import settings
from .redis_client import get_redis

logger = logging.getLogger(__name__)

WS_CHANNEL = "ws:notifications"
WS_INVALIDATE_CHANNEL = "ws:invalidate"
# Close code reported to clients whose sessions have been revoked
# (admin pressed ``invalidate-sessions``). Matches the ``4001`` code
# already used for first-message auth rejections so the frontend's
# generic 4001 handler picks it up without a special case.
WS_INVALIDATE_CLOSE_CODE = 4001
# Close code used when the connection's ``auth_date`` ages past
# ``WS_MAX_AGE_SECONDS``. Distinct from 4001 so the client can tell
# "your initData expired, reconnect with a fresh blob" apart from
# "your session was revoked, log in again".
WS_AGE_CLOSE_CODE = 4002
# Close code used as a safety net when the writer's ``send_text``
# itself hangs past ``WS_SEND_TIMEOUT_SECONDS`` — the per-message
# bounded deque already absorbs *bursty* slow consumers by dropping
# oldest, this code only fires for a fully wedged transport.
WS_SLOW_CONSUMER_CLOSE_CODE = 4003

# Tunables. Module-level so tests can monkey-patch them down to
# something quick (the production defaults are minute / hour scale,
# which would make a unit test sit forever).
#
# Bounded outgoing queue per socket. 100 messages × ~512 B per JSON
# event ≈ 50 KiB worst-case per slow consumer — acceptable; meanwhile
# a wide-awake client typically holds <1 message at a time.
#
# V11-L-1 — moved to ``Settings.ws_send_queue_size`` /
# ``Settings.ws_send_timeout_seconds`` so a deploy can resize the
# queue and the per-send ceiling via env var without a code change.
# The module-level names are kept as a thin alias because
# ``test_ws_hardening.py`` monkey-patches
# ``backend.app.ws.WS_SEND_QUEUE_SIZE`` directly; the runtime path
# (the deque ``maxlen=`` and the ``asyncio.wait_for(timeout=)`` call)
# reads the alias, so the monkey-patch keeps working. Both the
# alias and the underlying setting are import-time snapshots, so
# this is a deploy-time knob, not a runtime one.
WS_SEND_QUEUE_SIZE = settings.ws_send_queue_size
# Per-send timeout. The default is a long-but-finite ceiling so a
# half-open TCP socket can't hang the writer forever; the OS keep-
# alive will reap the underlying connection eventually but we don't
# want to wait that long with messages stacking up in our queue.
WS_SEND_TIMEOUT_SECONDS = settings.ws_send_timeout_seconds
# Connection-age cap (B.2). Telegram's ``initData`` is signed against
# the bot token and stamped with ``auth_date``; ``verify_init_data``
# rejects blobs older than ``settings.init_data_max_age_seconds`` at
# handshake time. The cap below ensures that *already-established*
# sockets don't outlive that window either.
#
# V11-H-7 — moved to ``Settings`` so production can tune both the cap
# and the sweep interval without a code change. The module-level
# names are kept as a thin alias for legacy tests that monkey-patch
# them. New call sites read ``settings.ws_max_age_seconds`` /
# ``settings.ws_age_check_interval_seconds`` directly so they pick
# up runtime overrides.
WS_MAX_AGE_SECONDS = settings.ws_max_age_seconds
WS_AGE_CHECK_INTERVAL_SECONDS = settings.ws_age_check_interval_seconds

# V11-L-14 — hard ceiling on a single Redis pub/sub envelope. The
# largest legitimate payload is the 4 KB-capped audit envelope plus
# wrapper IDs, so 64 KiB is ~16× headroom — enough to absorb future
# field growth without giving a malicious or buggy publisher room to
# OOM every subscriber.
_WS_MAX_ENVELOPE_BYTES = 64 * 1024


@dataclass
class _RecvRateState:
    """Per-socket inbound rate tracking (Comment 38)."""

    window_start: float = 0.0
    count: int = 0


@dataclass
class _SocketState:
    """Per-socket bookkeeping for the bounded-queue writer + age check."""

    user_id: int
    websocket: WebSocket
    auth_date_epoch: int | None
    queue: deque[str] = field(default_factory=lambda: deque(maxlen=WS_SEND_QUEUE_SIZE))
    # Signals the writer task that there's at least one new item in
    # ``queue``. ``deque.append`` doesn't expose a hook, so we have to
    # ``set()`` manually after every enqueue.
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    writer_task: asyncio.Task | None = None
    # Closed once we've decided this socket is dead — guards against
    # double-close races between the writer, the reaper, and the
    # endpoint handler.
    closed: bool = False
    # Cumulative count of frames the bounded queue dropped because the
    # consumer wasn't keeping up. Logged once per ramp-up so the
    # operator can correlate with client-side reconnect spam.
    dropped: int = 0
    recv_rate: _RecvRateState = field(default_factory=_RecvRateState)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, list[WebSocket]] = {}
        self._states: dict[int, _SocketState] = {}
        self._pubsub_task: asyncio.Task | None = None
        self._pubsub: Any = None
        self._age_task: asyncio.Task | None = None

    async def connect(
        self,
        user_id: int,
        websocket: WebSocket,
        auth_date_epoch: int | None = None,
    ) -> None:
        """Register an already-accepted socket and spin up its writer.

        ``auth_date_epoch`` is the ``auth_date`` field from the verified
        Telegram ``initData`` blob; it's optional so callers that
        haven't been updated (or tests that don't care about the age
        check) still work — but in those paths the reaper just won't
        evict the socket.
        """
        # The caller is expected to have already called ``websocket.accept()``
        # — the notifications endpoint accepts up-front so it can run a
        # first-message auth handshake before registering the socket.
        # Comment 38: socket cap per user.
        existing = self._connections.get(user_id, [])
        cap = settings.ws_max_sockets_per_user
        if cap and len(existing) >= cap:
            # V11-L-15 — structured-logging fields so the JSON-logger
            # downstream (Loki/Sentry) can pivot on event/user_id
            # without regexing the message body.
            logger.warning(
                "WS socket cap reached: user_id=%d cap=%d — rejecting",
                user_id,
                cap,
                extra={
                    "event": "ws.connect.socket_cap_reached",
                    "user_id": user_id,
                    "cap": cap,
                },
            )
            try:
                await websocket.close(code=4008, reason="Too many connections")
            except Exception:  # noqa: BLE001
                pass
            return

        self._connections.setdefault(user_id, []).append(websocket)
        state = _SocketState(
            user_id=user_id,
            websocket=websocket,
            auth_date_epoch=auth_date_epoch,
        )
        # Use ``id(websocket)`` because raw ``WebSocket`` objects from
        # Starlette aren't reliably hashable across all transports we
        # exercise in tests.
        self._states[id(websocket)] = state
        state.writer_task = asyncio.create_task(self._writer(state))
        # V11-L-15 — structured-logging fields so the JSON-logger
        # downstream (Loki/Sentry) can pivot on event/user_id and
        # the per-user socket count without regexing the message body.
        total = len(self._connections.get(user_id, []))
        logger.info(
            "WS connected: user_id=%d (total=%d)",
            user_id,
            total,
            extra={
                "event": "ws.connect.ok",
                "user_id": user_id,
                "total_sockets": total,
            },
        )

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        conns = self._connections.get(user_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            self._connections.pop(user_id, None)
        state = self._states.pop(id(websocket), None)
        if state is None:
            return
        state.closed = True
        # Drain the queue so the writer wakes, sees ``closed=True``, and
        # exits cleanly instead of waiting on ``wake`` forever.
        state.wake.set()
        task = state.writer_task
        if task is not None and not task.done():
            task.cancel()

    async def publish(self, user_id: int, data: dict[str, Any]) -> None:
        """Send to ``user_id``'s sockets, going through Redis if configured.

        With Redis: PUBLISH on ``ws:notifications`` so every backend
        instance forwards to its own local sockets. Without Redis: send
        directly to the local sockets we know about.
        """
        r = await get_redis()
        if r is None:
            await self._send_local(user_id, data)
            return
        envelope = json.dumps({"user_id": user_id, "data": data})
        try:
            await r.publish(WS_CHANNEL, envelope)
        except Exception:  # noqa: BLE001
            # V11-L-15 — structured-logging fields so the JSON-logger
            # downstream (Loki/Sentry) can pivot on event/user_id
            # without regexing the message body.
            logger.exception(
                "WS publish failed; falling back to local delivery",
                extra={"event": "ws.publish.failed", "user_id": user_id},
            )
            await self._send_local(user_id, data)

    async def invalidate_user(self, user_id: int) -> None:
        """Close every active socket for ``user_id``.

        Mirrors :meth:`publish`: with Redis we PUBLISH on
        ``ws:invalidate`` so every backend instance closes its local
        sockets; without Redis we just close the ones we hold. Called
        when the admin panel revokes a user's sessions so the user's
        notifications stop fanning out to a now-untrusted device.
        """
        r = await get_redis()
        if r is None:
            await self._close_local(user_id)
            return
        envelope = json.dumps({"user_id": user_id})
        try:
            await r.publish(WS_INVALIDATE_CHANNEL, envelope)
        except Exception:  # noqa: BLE001
            # V11-L-15 — structured-logging fields so the JSON-logger
            # downstream (Loki/Sentry) can pivot on event/user_id
            # without regexing the message body.
            logger.exception(
                "WS invalidate publish failed; falling back to local close",
                extra={"event": "ws.invalidate.publish_failed", "user_id": user_id},
            )
            await self._close_local(user_id)

    # ``send_to_user`` is kept for direct local delivery (used by the
    # pub/sub listener); routers should call ``publish`` instead.
    async def send_to_user(self, user_id: int, data: dict[str, Any]) -> None:
        await self.publish(user_id, data)

    async def _send_local(self, user_id: int, data: dict[str, Any]) -> None:
        """Enqueue ``data`` onto every local socket's outgoing queue.

        The writer task per socket pumps the queue into ``send_text``.
        Slow consumers can't stall fan-out: their ``deque`` is bounded,
        and an enqueue that overflows drops the oldest pending message
        instead of blocking the producer.
        """
        conns = self._connections.get(user_id, [])
        if not conns:
            return
        payload = json.dumps(data)
        for ws in conns:
            state = self._states.get(id(ws))
            if state is None or state.closed:
                continue
            self._enqueue(state, payload)

    def _enqueue(self, state: _SocketState, payload: str) -> None:
        """Append to the bounded queue; track + log drops on overflow.

        ``deque(maxlen=N)`` drops the *oldest* item when the
        ``N+1``-th is appended — there's no way to ask whether a drop
        happened beyond comparing ``len`` before and after. The
        ``dropped`` counter is logged once every 100 evictions per
        socket so operations sees a noisy consumer without flooding
        the log.
        """
        if len(state.queue) == state.queue.maxlen:
            state.dropped += 1
            if state.dropped == 1 or state.dropped % 100 == 0:
                # V11-L-15 — structured-logging fields so the JSON-
                # logger downstream (Loki/Sentry) can pivot on event/
                # user_id and the cumulative drop count without
                # regexing the message body.
                logger.warning(
                    "WS slow consumer: user_id=%d dropped=%d (queue cap=%d)",
                    state.user_id,
                    state.dropped,
                    state.queue.maxlen,
                    extra={
                        "event": "ws.writer.slow_consumer",
                        "user_id": state.user_id,
                        "dropped": state.dropped,
                        "queue_cap": state.queue.maxlen,
                    },
                )
        state.queue.append(payload)
        state.wake.set()

    async def _writer(self, state: _SocketState) -> None:
        """Drain ``state.queue`` into ``state.websocket.send_text``.

        Loops forever until ``state.closed`` flips true (set by
        :meth:`disconnect` or :meth:`_close_local`) or ``send_text``
        raises — at which point we mark the socket dead and bail.
        ``asyncio.wait_for`` bounds the per-send latency so a stuck
        TCP socket can't hang the queue indefinitely.
        """
        try:
            while True:
                await state.wake.wait()
                state.wake.clear()
                while state.queue:
                    if state.closed:
                        return
                    item = state.queue.popleft()
                    try:
                        await asyncio.wait_for(
                            state.websocket.send_text(item),
                            timeout=WS_SEND_TIMEOUT_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        # V11-L-15 — structured-logging fields so the
                        # JSON-logger downstream (Loki/Sentry) can
                        # pivot on event/user_id without regexing the
                        # message body.
                        logger.warning(
                            "WS writer: send timeout user_id=%d — closing socket",
                            state.user_id,
                            extra={
                                "event": "ws.writer.send_timeout",
                                "user_id": state.user_id,
                                "timeout_seconds": WS_SEND_TIMEOUT_SECONDS,
                            },
                        )
                        state.closed = True
                        try:
                            await state.websocket.close(
                                code=WS_SLOW_CONSUMER_CLOSE_CODE,
                                reason="Send timeout",
                            )
                        except Exception:  # noqa: BLE001
                            logger.debug(
                                "WS writer: close after timeout failed",
                                exc_info=True,
                                extra={
                                    "event": "ws.writer.close_after_timeout_failed",
                                    "user_id": state.user_id,
                                },
                            )
                        return
                    except Exception:  # noqa: BLE001
                        # ``send_text`` raises on a dead socket. The
                        # endpoint's receive loop will observe the same
                        # disconnect and call :meth:`disconnect`; we
                        # just stop pumping.
                        state.closed = True
                        return
                if state.closed:
                    return
        except asyncio.CancelledError:
            raise

    async def _close_local(self, user_id: int) -> None:
        """Close every socket attached to ``user_id`` on this instance.

        Snapshots the list first so iteration is stable while the socket
        handler (which holds the receive loop) removes itself via
        :meth:`disconnect` on the way out.
        """
        conns = list(self._connections.get(user_id, []))
        for ws in conns:
            state = self._states.get(id(ws))
            if state is not None:
                state.closed = True
                state.wake.set()
            try:
                await ws.close(code=WS_INVALIDATE_CLOSE_CODE, reason="Session revoked")
            except Exception:  # noqa: BLE001
                # V11-L-15 — structured-logging fields so the JSON-
                # logger downstream (Loki/Sentry) can pivot on event/
                # user_id without regexing the message body.
                logger.debug(
                    "WS close on invalidate failed",
                    exc_info=True,
                    extra={
                        "event": "ws.close.on_invalidate_failed",
                        "user_id": user_id,
                    },
                )
            finally:
                self.disconnect(user_id, ws)

    async def start_subscriber(self) -> None:
        """Subscribe to ``ws:notifications`` if Redis is available.

        Idempotent — calling twice does nothing the second time. The
        listener task is cancelled by :meth:`stop_subscriber` during
        application shutdown.

        Also boots the per-socket age-check reaper (B.2). It's not
        Redis-specific: even single-instance deployments want the
        12 h cap on stale ``auth_date`` connections.
        """
        if self._age_task is None or self._age_task.done():
            self._age_task = asyncio.create_task(self._age_check_loop())

        if self._pubsub_task is not None:
            return
        r = await get_redis()
        if r is None:
            return
        try:
            ps = r.pubsub()
            await ps.subscribe(WS_CHANNEL, WS_INVALIDATE_CHANNEL)
        except Exception:  # noqa: BLE001
            # V11-L-15 — structured-logging fields so the JSON-logger
            # downstream (Loki/Sentry) can pivot on event without
            # regexing the message body.
            logger.exception(
                "WS subscriber: subscribe failed; staying local-only",
                extra={"event": "ws.subscriber.subscribe_failed"},
            )
            return
        self._pubsub = ps
        self._pubsub_task = asyncio.create_task(self._listen(ps))

    async def stop_subscriber(self) -> None:
        task = self._pubsub_task
        ps = self._pubsub
        self._pubsub_task = None
        self._pubsub = None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if ps is not None:
            try:
                await ps.unsubscribe(WS_CHANNEL, WS_INVALIDATE_CHANNEL)
                await ps.aclose()
            except Exception:  # noqa: BLE001
                # V11-L-15 — structured-logging fields so the JSON-
                # logger downstream (Loki/Sentry) can pivot on event
                # without regexing the message body.
                logger.exception(
                    "WS subscriber: error during shutdown",
                    extra={"event": "ws.subscriber.shutdown_failed"},
                )

        age_task = self._age_task
        self._age_task = None
        if age_task is not None and not age_task.done():
            age_task.cancel()
            try:
                await age_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def _evict_expired_once(self) -> int:
        """Single sweep of the age-check reaper (B.2). Returns count evicted.

        Split out from :meth:`_age_check_loop` so tests can run one
        iteration deterministically without driving the 5-minute
        scheduler. Closes the socket but doesn't ``disconnect`` —
        the endpoint's receive loop will catch ``WebSocketDisconnect``
        and clean up state in the normal path.
        """
        cutoff = int(time.time()) - WS_MAX_AGE_SECONDS
        expired: list[_SocketState] = [
            s
            for s in list(self._states.values())
            if s.auth_date_epoch is not None and s.auth_date_epoch < cutoff and not s.closed
        ]
        for state in expired:
            # V11-L-15 — structured-logging fields so the JSON-logger
            # downstream (Loki/Sentry) can pivot on event/user_id/
            # auth_date_epoch without regexing the message body.
            logger.info(
                "WS age cap: closing user_id=%d auth_date=%d (cap=%ds)",
                state.user_id,
                state.auth_date_epoch or 0,
                WS_MAX_AGE_SECONDS,
                extra={
                    "event": "ws.age_cap.evict",
                    "user_id": state.user_id,
                    "auth_date_epoch": state.auth_date_epoch or 0,
                    "cap_seconds": WS_MAX_AGE_SECONDS,
                },
            )
            state.closed = True
            state.wake.set()
            try:
                await state.websocket.close(code=WS_AGE_CLOSE_CODE, reason="Auth expired")
            except Exception:  # noqa: BLE001
                logger.debug(
                    "WS age cap: close failed",
                    exc_info=True,
                    extra={
                        "event": "ws.age_cap.close_failed",
                        "user_id": state.user_id,
                    },
                )
        return len(expired)

    async def _age_check_loop(self) -> None:
        """Reap sockets whose ``auth_date`` aged past the cap (B.2).

        Telegram's ``initData`` is signed with an ``auth_date`` epoch
        and ``verify_init_data`` rejects blobs older than 24 h at
        *handshake* time. But the WebSocket itself can outlive that
        window — a socket that auth'd two days ago and is still TCP-
        connected keeps streaming notifications forever. This loop
        closes those sockets so the only way to keep listening is to
        reconnect with a fresh ``initData``.
        """
        try:
            while True:
                await asyncio.sleep(WS_AGE_CHECK_INTERVAL_SECONDS)
                try:
                    await self._evict_expired_once()
                except Exception:  # noqa: BLE001
                    # V11-L-15 — structured-logging fields so the
                    # JSON-logger downstream (Loki/Sentry) can pivot
                    # on event without regexing the message body.
                    logger.exception(
                        "WS age-check iteration failed",
                        extra={"event": "ws.age_cap.iteration_failed"},
                    )
        except asyncio.CancelledError:
            raise

    async def _listen(self, ps: Any) -> None:
        try:
            async for message in ps.listen():
                if message is None or message.get("type") != "message":
                    continue
                # V11-L-14 — size sanity-check on the envelope before
                # ``json.loads``. Redis pub/sub doesn't enforce a max
                # message size, but the WS notification envelopes we
                # send through this channel are always small (a JSON
                # blob with a couple of IDs + a payload). A malformed
                # or hostile publisher dumping a multi-MB string would
                # otherwise allocate the entire string in Python on
                # every backend instance before we even check it. The
                # cap below is well above legitimate traffic (the
                # largest notification payload is ~4 KB, capped by
                # audit-log encoding) but small enough to bound the
                # blast radius.
                raw = message.get("data")
                if isinstance(raw, (str, bytes)) and len(raw) > _WS_MAX_ENVELOPE_BYTES:
                    # V11-L-15 — structured-logging fields so the
                    # JSON-logger downstream (Loki/Sentry) can pivot
                    # on event/size without regexing the message
                    # body.
                    logger.warning(
                        "WS subscriber: oversized envelope (%d bytes) dropped",
                        len(raw),
                        extra={
                            "event": "ws.subscriber.oversized_envelope",
                            "envelope_bytes": len(raw),
                            "cap_bytes": _WS_MAX_ENVELOPE_BYTES,
                        },
                    )
                    continue
                channel = message.get("channel")
                if channel == WS_INVALIDATE_CHANNEL:
                    try:
                        envelope = json.loads(raw)
                        user_id = int(envelope["user_id"])
                    except (KeyError, ValueError, TypeError):
                        # V11-L-15 — structured-logging fields so the
                        # JSON-logger downstream (Loki/Sentry) can
                        # pivot on event without regexing the
                        # message body. ``raw`` is deliberately NOT
                        # in ``extra`` — it would explode log cardi‐
                        # nality on a hostile publisher.
                        logger.warning(
                            "WS subscriber: malformed invalidate envelope %r",
                            raw,
                            extra={
                                "event": "ws.subscriber.malformed_invalidate",
                            },
                        )
                        continue
                    try:
                        await self._close_local(user_id)
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "WS subscriber: local invalidate failed",
                            extra={
                                "event": "ws.subscriber.local_invalidate_failed",
                                "user_id": user_id,
                            },
                        )
                    continue
                try:
                    envelope = json.loads(raw)
                    user_id = int(envelope["user_id"])
                    data = envelope["data"]
                except (KeyError, ValueError, TypeError):
                    # V11-L-15 — same rationale as the invalidate
                    # branch above: ``raw`` stays out of ``extra``.
                    logger.warning(
                        "WS subscriber: malformed envelope %r",
                        raw,
                        extra={"event": "ws.subscriber.malformed_envelope"},
                    )
                    continue
                try:
                    await self._send_local(user_id, data)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "WS subscriber: local dispatch failed",
                        extra={
                            "event": "ws.subscriber.local_dispatch_failed",
                            "user_id": user_id,
                        },
                    )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception(
                "WS subscriber: listen loop crashed",
                extra={"event": "ws.subscriber.listen_loop_crashed"},
            )

    def check_recv_rate(self, websocket: WebSocket) -> bool:
        """Return True if the inbound rate is within limits."""
        state = self._states.get(id(websocket))
        if state is None:
            return True
        now = time.monotonic()
        rr = state.recv_rate
        if now - rr.window_start >= 1.0:
            rr.window_start = now
            rr.count = 0
        rr.count += 1
        return rr.count <= settings.ws_recv_max_messages_per_second

    async def send_heartbeat(self, websocket: WebSocket) -> None:
        """Send a ping/heartbeat frame."""
        try:
            await websocket.send_text('{"type":"ping"}')
        except Exception:  # noqa: BLE001
            pass


manager = ConnectionManager()
