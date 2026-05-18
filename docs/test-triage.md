# Test-suite triage — coverage gaps, brittle patterns, follow-ups

> Audit ref: **CI-4** (audit v11). Source: a systematic read across the
> 74 files in `tests/` (~18 000 lines).  This is the deliverable the
> audit asked for — not a rewrite, an inventory of what the suite
> actually catches and where it's thin.

## Setup quality (conftest / helpers)

`tests/conftest.py` is solid and worth keeping:

- **Real Postgres + real Alembic.** Tests run against a dedicated
  `garant_test` database, dropped/created under a session-level
  advisory lock so xdist workers serialise the bootstrap. The lock
  key (`hashtext('garant_test_db_bootstrap') = 1_075_088_959`) is
  *distinct* from the alembic-side key in `alembic/env.py` so the
  bootstrap doesn't deadlock against alembic's own migration lock.
- **Per-test truncate + reseed.** `_tables_to_truncate()` is derived
  from `Base.metadata.sorted_tables`, so a future model class is
  picked up automatically (V12-H6 — was previously a hand-edited
  tuple). `reset_engine_for_tests()` rebuilds the asyncpg pool on the
  current event loop, avoiding the "Future attached to a different
  loop" RuntimeError pytest-asyncio used to produce.
- **Random `ADMIN_TOTP_BYPASS` per invocation** (V12-H1). The
  bypass-sentinel never escapes the test process; helpers read the
  live env var so call sites stay unchanged.
- **`atexit` cleanup of `MEDIA_ROOT`** (V12-M9) — no more stray
  `/tmp/garant-pytest-*` accumulation across long-lived CI runners.
- **Narrow log mute** (V12-L11). Only `aiogram.dispatcher` and
  `uvicorn.access` are quieted; `backend.app.notifier` /
  `uvicorn.error` stay at WARNING so caplog-based assertions still
  fire on regressions.

## Patterns that are robust

These shapes show up across the suite and they are the right ones:

1. **`asyncio.gather()` race tests against real Postgres `FOR UPDATE`.**
   `test_critical_race_conditions.py`, `test_admin_2fa_replay.py`,
   `test_v5_b_wallet_withdrawals.py`. The serializing primitive is
   the DB, not the test runner, so the race shape is genuine — on
   the pre-fix branch the assertions reproducibly fail. The
   `_WEBHOOK_FANOUT=5` constant in `test_critical_race_conditions`
   is documented (≥5 is "authoritative", 2 is "enough"), which is
   exactly the kind of comment that pays for itself when CI is
   green but you're staring at a flake report.
2. **`monkeypatch` against module-level constants** for behaviour
   knobs (`WS_MAX_AGE_SECONDS`, `WS_SEND_QUEUE_SIZE`,
   `_CSP_DIRECTIVES`). pytest's auto-revert handles teardown. The
   constants are read from the module at call time, not captured at
   import time, so the patch is observed by the production code on
   each call.
3. **AST-driven meta-checks of `alembic/versions/`** in
   `test_v5_d_e_bucket.py` (`_migrations_with_numeric_narrowing_downgrade`,
   `test_concurrent_index_migrations_use_autocommit_and_concurrently`).
   These guard the migration contract by reading the source files
   rather than the DB state, so they keep working when migration
   bodies grow new statements.
4. **`fakeredis.aioredis` bound via `override_for_tests`.**
   `test_redis_backed.py`, `test_admin_2fa_replay.py`,
   `test_rate_limit_redis_integration.py`. The Redis claim path is
   actually exercised (not stubbed), and the fallback "no Redis
   bound" path is asserted separately so we don't accidentally
   regress to in-process-only.
5. **CSP snapshot test** (`test_csp_directives_match_expected_snapshot`)
   plus negative invariants (`'unsafe-inline'`/`'unsafe-eval'`/`*`
   forbidden). A weakening of the policy can't slip in unnoticed —
   either the literal snapshot diff fails, or one of the
   policy-shape tests fails.
6. **Compile-time DTO contract** between backend & frontend
   (`frontend/src/api/openapi.contract.test.ts`). Strict
   `as const satisfies T` — drift fails `tsc` before vitest ever
   runs.

## Patterns that are brittle (or *could* become brittle)

These aren't broken today but a future change can make them flake.
Each one is paired with the trigger that would cause the flake so a
future contributor knows what to do if the test starts going red.

### B-1. Bounded polling loops with hard-coded retry counts

Many WS / async tests poll until a state-change happens, capped by a
counter:

```python
for _ in range(50):
    if server.started: break
    await asyncio.sleep(0.05)   # 2.5 s budget
else:
    raise RuntimeError("uvicorn did not start within 2.5s")
```

`tests/conftest.py::ws_server` (50×50 ms = 2.5 s), several tests in
`test_ws_hardening.py` (20×50 ms = 1 s, 100×20 ms = 2 s), and
`test_critical_race_conditions.py` use this shape. The
budgets are generous on a quiet runner; on a heavily-loaded shared
runner (or a cold Docker pool spinning up at the same time as the
test) they can run out. **Trigger:** moving CI to a runner with
≤2 vCPU or sharing the runner with parallel image builds.
**Mitigation if it flakes:** scale the per-iteration sleep up
proportionally instead of bumping the count (we want a longer wall
clock, not more polling churn).

### B-2. Wall-clock dependent thresholds

`test_online_status_watermark.py::test_user_to_out_threshold_boundary_within_window`
asserts "5 min minus 5 s = online", which only passes if the test
itself finishes <5 s after the timestamp was set. Realistic on every
runner, but it's a real-time test rather than a frozen-time test
(no `freezegun`/`time-machine`). **Trigger:** GC pause, swap, or a
debugger pause between line 102 and 104. **Mitigation:** convert
to `freezegun` *if* we ever see it flake. Don't pre-emptively rewrite
— the test is cheap and reads honestly today.

### B-3. Concurrent overflow tests rely on writer-task scheduling

`test_ws_hardening.py::test_send_queue_drops_oldest_on_overflow`
needs the writer task to actually run between `mgr._send_local(0)`
and `mgr._send_local(1)` — otherwise no item ever pops off the queue
and the assertions about ordering get the wrong shape. The current
code does `if i == 0: await asyncio.sleep(0.01)` after the first
push to nudge the scheduler. **Trigger:** an event-loop refactor
(e.g. switch to uvloop, change of asyncio internals across Python
versions) that re-orders task wakeups. **Mitigation:** make the
yield explicit via `await asyncio.sleep(0)` between the first push
and the rest, instead of the 10 ms wall-clock sleep. Out of scope
for this audit — flagging only.

### B-4. `monkeypatch.setattr("backend.app.ws.WS_MAX_AGE_SECONDS", -2)`

These patches the *module attribute* — the production code reads
`from .ws import WS_MAX_AGE_SECONDS` indirectly via `manager` or
`WS_MAX_AGE_SECONDS` lookups in the same module. A refactor that
moves the constant under `settings.WS_MAX_AGE_SECONDS` would
silently make the patch a no-op (the test would still pass against
the *default* threshold for the same race shape, but a regression
that flipped the default could slip through). **Mitigation:** when
the constants migrate to `Settings`, the test must migrate to
`monkeypatch.setenv("WS_MAX_AGE_SECONDS", "-2")` plus a fresh
`Settings()` re-instantiation. None of this is needed today.

### B-5. `_PROVIDER_ID = "780011001"` in `test_concurrent_webhook_and_poll_credits_wallet_only_once`

The string is numeric because `poll_deposit_status` coerces it to
`int` for the CryptoBot `get_invoices` call. The previous value
(`"cb-race-webhook-poll-wallet-1"`) crashed the polling branch
silently. **Mitigation already in place:** the docstring documents
this. The risk is that a future test in the same file copies the
non-numeric form. **Action:** if we add a 4th test in this file,
factor `_PROVIDER_ID_PREFIX = "78001"` into a constant and require
all new IDs to be numeric strings. Cosmetic.

### B-6. Reseed-between-tests latency

`reset_db` autouse fixture truncates every table + reseeds.  On a
local laptop this adds ~50 ms per test; on Postgres-in-a-Docker-VM
in CI it adds ~150–250 ms.  Multiplied by ~520 tests, this is a
real chunk of the wall clock.  Two cheap optimisations exist —
neither is being requested by the audit, flagged here for the
backlog:

1. Skip the autouse reset for the dozen tests that touch no DB
   state (e.g. `test_csp_policy.py::test_csp_*` directly read the
   constant; `test_money_helpers.py`).  Decorate those with
   `@pytest.mark.no_reset` and short-circuit the fixture on the
   marker.
2. Drop the implicit `run_seed` from `reset_db` and have the few
   tests that need seed data call `seed_currencies(...)` /
   `seed_categories(...)` themselves.  Most tests don't read any
   seed-only row.

### B-7. `caplog.at_level(logging.DEBUG, logger=...)` + assertion on `levelno`

`test_v5_d_e_bucket.py::test_csp_report_*` checks
`all(r.levelno == logging.DEBUG for r in records)`.  A future
debug-only `logger.debug("...")` introduced to the same code path
(e.g. an entry-trace) would *also* be DEBUG and the assertion would
still pass — but the original `INFO` line might have been silently
dropped.  Stricter version: filter `records` to a known message
substring before checking the level.  Out of scope, flagged.

## Coverage gaps (highest-signal, ordered by risk)

These are the audit-shaped holes I can confirm by reading the suite.
None of them are open security findings (they're all already
documented elsewhere in the audit history); they're listed here so a
future contributor can pick one off the backlog without re-reading
the whole repo.

1. **No frontend e2e suite.**  The frontend layer has the contract
   test plus `client.test.ts` (the `ky` instance, ~12 tests).  We
   have zero Playwright / Cypress / Vitest-DOM coverage of the
   full user flow (login → set PIN → top up → create deal →
   complete).  The audit acknowledges this is out of scope for now;
   it's the single biggest gap.  `docs/runtime-validation.md` lists
   one of the unlocks — runtime validators on the API client.
2. **No load / stress test for the rate-limiter Lua script.**
   `test_rate_limit_redis_integration.py` covers the happy path
   and the off-by-one boundary; we don't actually saturate the
   sliding window under fakeredis the way Redis itself would
   (fakeredis runs the Lua synchronously).  A regression in the
   Lua source would surface in production before CI sees it.
   **Action:** if we ever start tuning the script, add a "stress"
   marker that runs against a real Redis container with `RUN_REAL_REDIS=1`.
3. **No `freezegun` / `time-machine`.**  Most temporal tests rely
   on the real clock (B-2 above).  Convertible if we ever see real
   flakes, not before.
4. **No coverage of the SPA fallback path under a built `frontend/dist`.**
   `test_spa_fallback_traversal.py` exercises the traversal-safe
   path but it doesn't assert that the SPA shell is *served* —
   because in CI `frontend/dist` doesn't exist.  This is by design
   today (the build is a separate workflow) but it means a
   regression that broke the SPA mount would only be caught in
   prod.  **Action:** if/when the build moves into the pytest job,
   add a positive serve test.
5. **No `pytest-randomly`.**  Tests are well-isolated by
   `reset_db` but they run in deterministic file order.  Random
   ordering would catch a future regression where one test
   accidentally writes to a module-level cache another reads.
   **Action:** add `pytest-randomly` as a dev-dependency and run
   it on the nightly workflow only at first — running it on every
   PR would flake out the first time the seed exposes a hidden
   ordering dep.

## Items the audit specifically mentions

- **V12-I1** — "Tests not read line-by-line (~70 files), see V12-I1".
  This document IS that read.  Findings are above; nothing surfaced
  warrants an immediate PR.  Each item has an explicit
  `**Mitigation**` / `**Action**` clause so a future contributor
  has a starting line.
- **CI-4** — same as V12-I1, but tagged as a "coverage gap" rather
  than a "test reading" task.  The gap inventory in §"Coverage
  gaps" above is the deliverable.
- **A-8** — covered by `docs/runtime-validation.md`.  The
  contract test (`openapi.contract.test.ts`) plus the `check:api-drift`
  CI gate close most of A-8; the gap is documented and the migration
  recipe is laid out for when we want to take the rest.
- **L-10** — covered by `docs/audit-markers.md`.  Inline V5-X-Y
  prefixes stripped from production code; tests stay as-is because
  the audit bucket IS the test file organisation.

## What I did NOT change

To keep this PR scoped to the audit items the user asked for
(`V12-I7`, `V12-L12`, `L-10`, `A-5`, `A-8`, `CI-4`):

- No test was deleted, renamed, or rewritten.
- No `freezegun`/`pytest-randomly` was added.
- No autouse fixture was changed (in particular `reset_db` keeps
  its current behaviour even though §B-6 flags a future
  optimisation).
- No new test was added.  This is an inventory pass, not a coverage
  pass.  If any §"Coverage gaps" item escalates, open a focused PR
  for that single gap rather than batching it with audit cleanups.
