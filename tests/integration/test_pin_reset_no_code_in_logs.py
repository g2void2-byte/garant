"""V5-A-7 — preventive log-leak regression for the PIN reset code path.

The plaintext PIN-reset code is generated in
``backend.app.routers.pin.pin_reset_request``, embedded into the DM
``text`` passed to ``send_dm``, and the recipient's Telegram client is
the only legitimate place it appears. These tests lock in the
invariant that no logger anywhere on this code path captures the code:

* Test 1 monkeypatches ``generate_reset_code`` to return a known
  sentinel, attaches a ``caplog`` handler to every logger touched by
  the request (``backend.app.routers.pin``,
  ``backend.app.notifier``, ``backend.app.bot.notify``), drives the
  request, and asserts the sentinel does not appear in any captured
  log record (raw ``msg``, formatted message, positional ``args``, or
  ``extra``-style attributes on the record).
* Test 2 additionally stubs ``send_dm`` so we can assert it WAS called
  with the sentinel inside its ``text`` argument (the user must still
  receive the code) while no logger captured it.

If a future maintainer adds ``logger.info(text)`` or
``logger.exception("...", extra={"text": text})`` to any of these
modules, both tests will fail. The conftest ``_quiet_logs`` fixture
sets these loggers to CRITICAL by default; we re-enable DEBUG capture
explicitly here so even debug-level leaks would be caught.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from unittest.mock import AsyncMock

from sqlalchemy import select

from tests.helpers import (
    auth_headers,
    credit_balance,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)

# Sentinel must look like a real 6-digit reset code (matches
# ``RESET_CODE_LEN`` in backend.app.pin) so the substring search is
# narrow enough to be meaningful but wide enough to catch every
# representation the logger might produce.
SENTINEL_CODE = "654321"

_LOGGER_NAMES = (
    "backend.app.routers.pin",
    "backend.app.notifier",
    "backend.app.bot.notify",
)


def _record_contains_sentinel(record: logging.LogRecord, sentinel: str) -> bool:
    """Return True iff ``sentinel`` appears anywhere on the record.

    Checks the raw format string (``record.msg``), the rendered
    message (``record.getMessage()``), each positional argument
    (``record.args``), and the full ``__dict__`` so an
    ``extra={"code": ...}`` style leak would also be caught.
    """
    if sentinel in str(record.msg or ""):
        return True
    try:
        if sentinel in record.getMessage():
            return True
    except (TypeError, ValueError):
        # Bad format string — fall through to args/dict checks.
        pass
    args = record.args
    if args is not None:
        if isinstance(args, dict):
            iterable = args.values()
        elif isinstance(args, (tuple, list)):
            iterable = args
        else:
            iterable = (args,)
        for value in iterable:
            if sentinel in str(value):
                return True
    if sentinel in str(record.__dict__):
        return True
    return False


def _assert_no_sentinel_in_logs(caplog_records, sentinel: str) -> None:
    leaks: list[str] = []
    for rec in caplog_records:
        if rec.name not in _LOGGER_NAMES:
            continue
        if _record_contains_sentinel(rec, sentinel):
            leaks.append(
                f"logger={rec.name} level={rec.levelname} "
                f"msg={rec.msg!r} args={rec.args!r} dict={rec.__dict__!r}"
            )
    assert not leaks, "PIN reset code leaked into logs:\n" + "\n".join(leaks)


async def test_pin_reset_request_does_not_log_plaintext_code(client, caplog, monkeypatch):
    """The plaintext reset code must never appear in any logger call."""
    import backend.app.routers.pin as pin_router

    # Force a deterministic sentinel so we know exactly which substring
    # to search for in captured log records.
    monkeypatch.setattr(pin_router, "generate_reset_code", lambda: SENTINEL_CODE)

    # Conftest stubs ``notifier._safe_send_dm`` to a noop, but the
    # ``pin_reset_request`` handler calls ``send_dm`` directly via
    # ``from ..bot.notify import send_dm``, so the local symbol bound
    # at module-import time is what we patch. Without this stub the
    # real aiogram bot would spin up an aiohttp session against a fake
    # token and crash with "Event loop is closed". Returning True
    # keeps the handler off its ``logger.warning`` "delivery failed"
    # branch (which would log only ``user.id`` anyway, but we don't
    # want to depend on that here).
    monkeypatch.setattr(pin_router, "send_dm", AsyncMock(return_value=True))

    # Override the autouse ``_quiet_logs`` fixture so even DEBUG-level
    # records on these loggers reach caplog. A leak at any level must
    # fail the test.
    for name in _LOGGER_NAMES:
        caplog.set_level(logging.DEBUG, logger=name)

    init = signed_init_data(9701, "no-log-leak")
    await setup_pin(client, init)

    with caplog.at_level(logging.DEBUG):
        resp = await client.post(
            "/api/pin/reset/request",
            headers=auth_headers(init),
        )
    assert resp.status_code == 200, resp.text

    _assert_no_sentinel_in_logs(caplog.records, SENTINEL_CODE)


async def test_send_dm_is_called_with_plaintext_code_but_not_logged(client, caplog, monkeypatch):
    """Sanity check: the user does receive the code via ``send_dm``,
    but no logger captures it. Together with the previous test this
    proves the leak path is closed end-to-end (the code reaches the DM
    transport and nothing else)."""
    import backend.app.routers.pin as pin_router

    monkeypatch.setattr(pin_router, "generate_reset_code", lambda: SENTINEL_CODE)

    # Conftest stubs ``notifier._safe_send_dm`` to a noop, but the
    # ``pin_reset_request`` handler calls ``send_dm`` directly via
    # ``from ..bot.notify import send_dm``, so the local symbol bound
    # at module-import time is what we patch. Returning True keeps the
    # handler off its ``logger.warning`` "delivery failed" branch.
    send_dm_spy = AsyncMock(return_value=True)
    monkeypatch.setattr(pin_router, "send_dm", send_dm_spy)

    for name in _LOGGER_NAMES:
        caplog.set_level(logging.DEBUG, logger=name)

    init = signed_init_data(9702, "no-log-leak-2")
    await setup_pin(client, init)

    with caplog.at_level(logging.DEBUG):
        resp = await client.post(
            "/api/pin/reset/request",
            headers=auth_headers(init),
        )
    assert resp.status_code == 200, resp.text

    # send_dm WAS called with the sentinel in its ``text`` argument —
    # the user must still receive the code via the legitimate DM
    # channel.
    assert send_dm_spy.await_count == 1, send_dm_spy.await_args_list
    assert send_dm_spy.await_args is not None
    args, kwargs = send_dm_spy.await_args
    # ``send_dm(tg_user_id, text)`` — text is the second positional.
    text_arg = args[1] if len(args) >= 2 else kwargs.get("text", "")
    assert SENTINEL_CODE in text_arg, "send_dm must receive the plaintext code in its text argument"

    # …yet no logger on the request path captured it.
    _assert_no_sentinel_in_logs(caplog.records, SENTINEL_CODE)


async def test_paid_pin_reset_delivery_failure_does_not_charge_or_store_code(
    client,
    monkeypatch,
):
    """A paid reset must not debit USD unless the reset code was delivered."""
    import backend.app.routers.pin as pin_router
    from backend.app.db import async_session
    from backend.app.models import Currency, User, UserBalance

    monkeypatch.setattr(pin_router, "send_dm", AsyncMock(return_value=False))

    init = signed_init_data(9703, "paid-reset-undelivered")
    await setup_pin(client, init)
    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 9703)
        await credit_balance(session, user_id, "USD", 10.0)

    resp = await client.post(
        "/api/pin/reset/paid",
        headers=auth_headers(init),
    )
    assert resp.status_code == 502, resp.text
    assert "Баланс не списан" in resp.json()["detail"]

    async with async_session() as session:
        user_id = await get_user_id_by_tg(session, 9703)
        user = await session.get(User, user_id)
        assert user is not None
        assert user.pin_reset_code_hash is None
        assert user.pin_reset_expires is None

        balance = (
            await session.execute(
                select(UserBalance)
                .join(Currency, Currency.id == UserBalance.currency_id)
                .where(UserBalance.user_id == user_id, Currency.code == "USD")
            )
        ).scalar_one()
        assert Decimal(str(balance.amount)) == Decimal("10.00000000")
