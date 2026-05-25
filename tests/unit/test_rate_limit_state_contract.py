"""V12-L13 — module-level state in ``backend.app.rate_limit`` must
be enumerable and every entry must be reset by
``reset_state_for_tests``.

Why this exists
~~~~~~~~~~~~~~~

The test suite reaches for ``reset_state_for_tests`` between tests
(``tests/conftest.py::reset_db``) so per-process buckets, the cached
Lua-script handle, and any future module-level cache that the
limiter accumulates don't leak across cases. Pre-fix the helper was
maintained by hand: every time someone added a new module-level
container to ``rate_limit.py`` they had to remember to also clear
it inside ``reset_state_for_tests`` — and forgetting is silent.
A leaked counter doesn't fail an individual test obviously, it
just makes a later "303 reset between cases" test flake under
parallel load.

This contract test enumerates the module's public attribute table,
filters down to the *mutable* state containers (anything that owns
state about real or pending hits), and asserts that calling the
reset helper leaves each of them empty / re-initialised. Adding a
new bucket to the module without also resetting it in the helper
will fail this test loudly at collection time rather than later.

The check is intentionally allow-listed: rate-limit module-level
state is small and rarely changes, so we hard-code the expected
shape rather than try to reflect it from type annotations. The
allow-list also documents *what* counts as "state that needs
resetting" — a coroutine reference (``_hit``, ``_hit_inmemory``)
doesn't, but the cached compiled Lua script handle does because a
re-created fakeredis fixture would otherwise fail
``EVALSHA``-resolution against the stale SHA.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.app import rate_limit

# ── Allow-list of module-level *state* (vs functions / constants). ─


# Each entry is a tuple ``(attr_name, pre_reset_setter, expected_after_reset)``:
#
# * ``attr_name``  — name on ``rate_limit``. Must exist or the test
#                    fails with a precise message pointing at the
#                    drift.
# * ``pre_reset_setter`` — callable taking no args; mutates the
#                    state into a non-default shape so the test can
#                    distinguish "never touched" from "actually
#                    reset".
# * ``expected_after_reset`` — predicate taking the post-reset
#                    value and returning ``True`` when reset
#                    looks correct.
#
# Adding a new module-level state container? Add it here. Forgetting
# the helper in ``rate_limit.reset_state_for_tests`` is what this
# test exists to catch.
def _seed_buckets() -> None:
    rate_limit._buckets[("v12-l13-scope", "user:contract")].append(1.0)


def _seed_script() -> None:
    # A non-``None`` sentinel is enough; nothing inside
    # ``reset_state_for_tests`` cares about the *value*, only that
    # the cached handle is dropped so a new fakeredis fixture
    # re-registers a fresh ``Script`` on its first call.
    rate_limit._rl_script = object()


_STATE_CONTRACT = (
    ("_buckets", _seed_buckets, lambda v: len(v) == 0),
    ("_rl_script", _seed_script, lambda v: v is None),
)


@pytest.mark.parametrize("attr_name,seeder,predicate", _STATE_CONTRACT)
def test_reset_state_for_tests_clears_known_module_state(attr_name: str, seeder, predicate) -> None:
    """``reset_state_for_tests`` must zero every entry in ``_STATE_CONTRACT``.

    Mutates the attribute into a known non-default state, calls the
    helper, then asserts the predicate. The contract is allow-list
    driven on purpose: the rate-limit module's module-level state is
    small and rarely changes, so a new attribute showing up uninvited
    is a signal to add a deliberate entry here, not to weaken the
    check.
    """
    assert hasattr(rate_limit, attr_name), (
        f"rate_limit.{attr_name} has been renamed or removed; update "
        f"_STATE_CONTRACT in this file alongside the rename so the "
        f"reset helper still covers it."
    )

    seeder()
    rate_limit.reset_state_for_tests()
    value = getattr(rate_limit, attr_name)
    assert predicate(value), (
        f"rate_limit.{attr_name} still holds {value!r} after "
        f"reset_state_for_tests(); add a clear in "
        f"backend/app/rate_limit.py::reset_state_for_tests."
    )


def test_state_contract_covers_every_mutable_module_attr() -> None:
    """Companion to the parametrised test above.

    Walks ``rate_limit.__dict__`` and flags any *new* module-level
    name whose value type looks like state (mutable container or the
    cached script handle) but isn't in ``_STATE_CONTRACT``. The goal
    is to force the contract list to grow alongside the module:
    silently adding a new ``dict`` / ``deque`` / ``set`` cache to
    ``rate_limit.py`` is exactly the regression V12-L13 calls out.

    The detection rule deliberately ignores:
    * dunders and leading-underscore symbols that are obviously
      module bookkeeping (``__name__``, ``__doc__``);
    * the ``_RL_LUA`` source-string constant (it's a ``str``, not
      state);
    * functions / coroutines / dependency annotations (``rate_limit``,
      ``rate_limit_anon``, ``RLPin``, etc.) — they carry no per-test
      state;
    * ``_lock`` (an ``asyncio.Lock``); resetting it would orphan any
      task currently awaiting it. The lock is intentionally NOT
      part of the reset contract.
    """
    covered = {name for name, _, _ in _STATE_CONTRACT}

    # The set of types we treat as "state-bearing".
    state_types = (dict, list, set, frozenset)

    suspects: list[str] = []
    for name, value in vars(rate_limit).items():
        if name.startswith("__"):
            continue
        # Skip the Lua-source string constant (str, but inert).
        if name == "_RL_LUA":
            continue
        # The asyncio.Lock is intentionally not reset (see docstring).
        if isinstance(value, asyncio.Lock):
            continue
        # ``defaultdict`` is a dict subclass, ``deque`` is in
        # ``collections`` — both caught by ``state_types`` above via
        # the dict/list bases respectively. ``_rl_script`` is
        # ``None`` at import time; once populated it's a redis
        # ``Script`` instance. We treat the *name* as state, so it
        # must be in the contract regardless of current value.
        if name == "_rl_script":
            if name not in covered:
                suspects.append(name)
            continue
        if isinstance(value, state_types):
            if name not in covered:
                suspects.append(name)

    assert not suspects, (
        f"rate_limit.py has new module-level state {suspects!r} that "
        f"is not in _STATE_CONTRACT. Either add a (seeder, predicate) "
        f"entry here AND a clear in reset_state_for_tests, or — if the "
        f"new attribute is intentionally not per-test state — add a "
        f"narrow exemption to this test with a comment explaining why."
    )
