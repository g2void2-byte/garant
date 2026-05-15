"""Comment 47 (atomic Lua) and Comment 51 (sliding window) — focused
regressions on the rate-limit semantics.

Two failure modes the previous fixed-window + INCR/EXPIRE limiter had:

* **Comment 51** — a fixed window keyed on ``floor(t / window)`` lets
  through ``2 * limit`` hits over a ``window``-second span straddling
  the bucket boundary. For ``RLPin`` (5/60s) that is 10 attempts in
  ~100 ms which materially helps a PIN brute-force.
* **Comment 47** — the previous ``INCR`` + ``EXPIRE`` pair was two
  round-trips. A dropped ``EXPIRE`` left the counter without a TTL
  and the principal was blocked forever.

The fix unifies both backends on a **sliding window**: the in-process
backend uses a ``deque`` of hit timestamps, the Redis backend uses a
ZSET trimmed by a Lua script (atomic eviction + ZADD + PEXPIRE in one
RTT).

Strategy: drive ``rate_limit._hit_inmemory`` with a patched
``time.monotonic`` so the test can deterministically place hits at
specific points in the sliding window. The behavioural contract is
the same on the Redis backend (validated separately in
``test_redis_backed.py``), so a pure in-memory clock walk is enough
to lock down the sliding-vs-fixed difference.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.app import rate_limit


@pytest.fixture(autouse=True)
def _reset():
    """The limiter caches buckets per-process. Tests share that
    storage so a stale entry from another test would leak into the
    fixture clock here — reset before and after each case."""
    rate_limit.reset_state_for_tests()
    yield
    rate_limit.reset_state_for_tests()


def _patch_monotonic(monkeypatch, clock: list[float]) -> None:
    """Pin ``time.monotonic`` to ``clock[0]`` so the test can advance
    the simulated wall clock by reassigning ``clock[0]``. The limiter
    reads ``time.monotonic`` from the ``time`` module imported inside
    ``backend.app.rate_limit``, so we patch the symbol on the
    rate-limit module's bound ``time`` reference."""
    import time as _time

    monkeypatch.setattr(_time, "monotonic", lambda: clock[0])


async def test_in_memory_admits_then_blocks_within_one_window(monkeypatch):
    """Baseline: 5 hits at t=0 with a 60s window. The 6th hit at
    t=0+ε must be rejected — same as the legacy fixed-window
    behaviour for the simple case."""
    clock = [1000.0]
    _patch_monotonic(monkeypatch, clock)

    for _ in range(5):
        await rate_limit._hit("sliding-base", "user:1", limit=5, window=60.0)

    clock[0] = 1000.001
    with pytest.raises(HTTPException) as exc:
        await rate_limit._hit("sliding-base", "user:1", limit=5, window=60.0)
    assert exc.value.status_code == 429


async def test_in_memory_admits_after_window_elapses(monkeypatch):
    """Comment 51 — once the *oldest* hit ages out past the window,
    a fresh hit must be admitted again. This is the property the
    fixed-window backend already had (kind of) — the regression
    target here is that the sliding backend doesn't *over*-block."""
    clock = [1000.0]
    _patch_monotonic(monkeypatch, clock)

    for _ in range(5):
        await rate_limit._hit("sliding-expiry", "user:1", limit=5, window=60.0)

    # Advance just past the window: the entry at t=1000 is now older
    # than 60s, so it must be evicted and the new hit must pass.
    clock[0] = 1060.5
    await rate_limit._hit("sliding-expiry", "user:1", limit=5, window=60.0)


async def test_in_memory_blocks_at_boundary_inside_window(monkeypatch):
    """Comment 51 (H) — the bug the sliding window closes.

    Place all 5 hits at t=0, then attempt one more at t=59.5 (still
    within the 60s window). The legacy fixed-window backend (bucket
    boundary at t=60) would happily admit this and then admit
    another 5 in the next bucket starting at t=60.1 — i.e. 11 hits
    over ~0.5 seconds straddling the boundary instead of the
    expected 5. The sliding window correctly counts every entry
    still inside ``[now - window, now]`` and 429s.
    """
    clock = [1000.0]
    _patch_monotonic(monkeypatch, clock)

    for _ in range(5):
        await rate_limit._hit("sliding-boundary", "user:1", limit=5, window=60.0)

    # 59.5s after the first hit — still inside the window.
    clock[0] = 1000.0 + 59.5
    with pytest.raises(HTTPException) as exc:
        await rate_limit._hit("sliding-boundary", "user:1", limit=5, window=60.0)
    assert exc.value.status_code == 429


async def test_in_memory_only_aged_out_slots_become_available(monkeypatch):
    """Comment 51 (H) follow-up: sliding-window must release slots
    one at a time as each individual hit ages out — not all at once
    on the next bucket boundary (which is the fixed-window failure
    mode).

    Place 5 hits spaced 1 second apart at t=1000, 1001, 1002, 1003,
    1004. Advance to t=1061.5 — only the hit at t=1000 has aged
    past the 60s window. So exactly ONE new hit must be admitted and
    the next is 429'd because 5 are still in the rolling window.
    Advancing to t=1062.5 ages out the t=1001 hit too — another
    slot opens up. A fixed-window backend would either keep
    everything blocked until t=1060 (then admit 5 at once) or
    admit at t=1060 onwards regardless of the exact entries.
    """
    clock = [1000.0]
    _patch_monotonic(monkeypatch, clock)

    # 5 hits placed 2 seconds apart at t=1000, 1002, 1004, 1006, 1008
    # so the eviction check (``bucket[0] <= now - window``) walks one
    # entry at a time as the clock crosses each anniversary.
    for offset in range(0, 10, 2):
        clock[0] = 1000.0 + offset
        await rate_limit._hit("sliding-stagger", "user:1", limit=5, window=60.0)

    # cutoff = 1060.5 - 60 = 1000.5 → only the t=1000 hit evicts.
    clock[0] = 1060.5
    await rate_limit._hit("sliding-stagger", "user:1", limit=5, window=60.0)
    # Bucket now holds {1002, 1004, 1006, 1008, 1060.5} → cap reached.
    with pytest.raises(HTTPException) as exc:
        await rate_limit._hit("sliding-stagger", "user:1", limit=5, window=60.0)
    assert exc.value.status_code == 429

    # Advance to t=1062.5 → cutoff=1002.5, only t=1002 ages out next.
    clock[0] = 1062.5
    await rate_limit._hit("sliding-stagger", "user:1", limit=5, window=60.0)
    with pytest.raises(HTTPException) as exc:
        await rate_limit._hit("sliding-stagger", "user:1", limit=5, window=60.0)
    assert exc.value.status_code == 429


async def test_in_memory_principals_are_isolated(monkeypatch):
    """Sanity: the sliding-window key is per ``(scope, principal)``.
    User A saturating their bucket must not lock out user B in the
    same scope."""
    clock = [1000.0]
    _patch_monotonic(monkeypatch, clock)

    for _ in range(5):
        await rate_limit._hit("sliding-iso", "user:a", limit=5, window=60.0)

    clock[0] = 1000.001
    with pytest.raises(HTTPException):
        await rate_limit._hit("sliding-iso", "user:a", limit=5, window=60.0)
    # B is on their own bucket; goes through.
    await rate_limit._hit("sliding-iso", "user:b", limit=5, window=60.0)


async def test_retry_after_header_reflects_oldest_hit(monkeypatch):
    """``_raise_429`` derives ``Retry-After`` from the oldest entry
    in the bucket: the principal can retry once that entry ages out.
    Pre-sliding-window, the retry hint was anchored to the fixed
    bucket boundary which could be wildly off if hits landed near
    the boundary."""
    clock = [1000.0]
    _patch_monotonic(monkeypatch, clock)

    for _ in range(3):
        await rate_limit._hit("sliding-retry", "user:1", limit=3, window=30.0)

    # 1 second later: oldest hit was at t=1000, retry should hint
    # roughly window − 1 = ~29s remaining.
    clock[0] = 1001.0
    with pytest.raises(HTTPException) as exc:
        await rate_limit._hit("sliding-retry", "user:1", limit=3, window=30.0)
    assert exc.value.status_code == 429
    retry_after = int(exc.value.headers["Retry-After"])
    # Allow ±1 second slop because ``_raise_429`` does
    # ``int(retry_after) + 1`` for headroom.
    assert 28 <= retry_after <= 31, retry_after
