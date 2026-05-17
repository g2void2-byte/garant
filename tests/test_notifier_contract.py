"""Contract tests for the test-suite-internal Telegram-DM stub (V12-M7).

``conftest.py`` installs an autouse fixture that replaces
``backend.app.notifier._safe_send_dm`` with a no-op so the test suite
never hits the live Telegram API.

The stub is keyed by *attribute name*: if a future refactor renames the
private helper (or moves it under a class, or drops the leading
underscore), the autouse fixture silently fails to install and any
``notifier.push(...)`` call in tests starts firing real DMs against the
fake bot token — flaky stderr, occasional rate-limit errors against
``api.telegram.org``, and (worst case) leakage of test-fixture data into
a real Telegram chat if someone is debugging with a production token.

This file pins the contract so that breakage shows up as a *test
failure with a clear message* rather than as flaky tests downstream:

1. ``_safe_send_dm`` exists as a module-level attribute.
2. It is a coroutine function (so ``asyncio.create_task`` over its
   return value works the same way ``notifier.dispatch_after_commit``
   schedules it).
3. The autouse stub has actually replaced it for the duration of the
   test (i.e. the fixture wiring is live).
"""

from __future__ import annotations

import asyncio
import inspect


def test_safe_send_dm_exists_on_notifier_module() -> None:
    """The autouse stub patches by attribute name; the name must exist."""
    import backend.app.notifier as notifier

    assert hasattr(notifier, "_safe_send_dm"), (
        "backend.app.notifier._safe_send_dm is missing — the autouse "
        "DM stub in tests/conftest.py patches by name and silently "
        "falls back to no patching if the symbol is renamed. Update "
        "tests/conftest.py::_stub_telegram_dm to match the new name."
    )


def test_safe_send_dm_is_coroutine_function() -> None:
    """``notifier.dispatch_after_commit`` wraps it in ``create_task``."""
    import backend.app.notifier as notifier

    assert inspect.iscoroutinefunction(notifier._safe_send_dm), (
        "_safe_send_dm must be an ``async def`` so the "
        "``asyncio.create_task(_safe_send_dm(...))`` call site in "
        "notifier.dispatch_after_commit schedules a coroutine."
    )


async def test_autouse_stub_is_active() -> None:
    """The autouse fixture must replace _safe_send_dm before this test runs.

    We assert by calling it: the no-op stub returns ``None`` immediately;
    the real implementation would attempt to import ``backend.app.bot.notify``
    and dispatch through aiogram against the (fake) bot token, which we
    don't want happening in pytest.
    """
    import backend.app.notifier as notifier

    result = await notifier._safe_send_dm(123456789, "<b>test</b> body")
    assert result is None
    assert asyncio.iscoroutinefunction(notifier._safe_send_dm)
