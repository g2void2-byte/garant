"""Unit tests for the canonical money helpers — H-2 contract.

``backend/app/money.py`` is the single source of truth for the
``Numeric(28, 8)`` shape and the ``ROUND_HALF_EVEN`` rounding mode
used on every money-output site. These tests pin the contract:

* ``MONEY_PRECISION`` / ``MONEY_SCALE`` keep the canonical
  ``Numeric(28, 8)`` shape exposed for callers.
* ``MONEY_ROUNDING`` is ``ROUND_HALF_EVEN`` (banker's rounding) —
  not the implicit thread-local default that ``Decimal.quantize``
  would otherwise read.
* ``to_decimal`` routes ``float`` through ``str`` so the binary
  representation noise of ``0.1`` never leaks into a stored or
  serialised value.
* ``quantize_money`` always passes ``ROUND_HALF_EVEN`` regardless of
  the surrounding ``decimal`` context.

No HTTP / DB plumbing — these tests run in-process and stay fast.
"""

from __future__ import annotations

import decimal
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

import pytest

from backend.app.money import (
    MONEY_PRECISION,
    MONEY_ROUNDING,
    MONEY_SCALE,
    quantize_money,
    to_decimal,
)


def test_canonical_constants() -> None:
    """The canonical shape is pinned at ``Numeric(28, 8)`` with
    ``ROUND_HALF_EVEN``. A drift here forces an explicit migration
    + audit conversation, not a silent change.
    """
    assert MONEY_PRECISION == 28
    assert MONEY_SCALE == 8
    assert MONEY_ROUNDING == ROUND_HALF_EVEN


def test_to_decimal_routes_floats_through_str() -> None:
    """``Decimal(0.1)`` constructs the full binary fan-out
    (``0.1000000000000000055511151231...``); ``to_decimal(0.1)``
    must go through ``str`` so it equals ``Decimal('0.1')``.
    """
    assert to_decimal(0.1) == Decimal("0.1")
    assert to_decimal(0.2) == Decimal("0.2")
    # Identity for an existing Decimal — no needless re-encoding.
    existing = Decimal("123456789012345678.12345678")
    assert to_decimal(existing) is existing
    # int + str inputs round-trip exactly.
    assert to_decimal(7) == Decimal(7)
    assert to_decimal("0.12345678") == Decimal("0.12345678")


def test_quantize_money_uses_round_half_even() -> None:
    """Banker's rounding rounds .5 to the nearest even digit, so
    ``0.125 -> 0.12`` (down) and ``0.135 -> 0.14`` (up). Asserting
    both cases pins the rounding mode against a silent flip to
    ``ROUND_HALF_UP``.
    """
    assert quantize_money(Decimal("0.125"), 2) == Decimal("0.12")
    assert quantize_money(Decimal("0.135"), 2) == Decimal("0.14")


def test_quantize_money_ignores_thread_local_rounding_mode() -> None:
    """A caller that flipped ``decimal.getcontext().rounding`` to
    ``ROUND_HALF_UP`` must NOT shift the money output. The helper
    pins ``ROUND_HALF_EVEN`` on every call.
    """
    previous = decimal.getcontext().rounding
    try:
        decimal.getcontext().rounding = ROUND_HALF_UP
        # Under ROUND_HALF_UP this would be 0.13; under HALF_EVEN
        # it stays at 0.12 (nearest even digit at the boundary).
        assert quantize_money(Decimal("0.125"), 2) == Decimal("0.12")
    finally:
        decimal.getcontext().rounding = previous


def test_quantize_money_respects_per_currency_decimals() -> None:
    """``decimals`` is per-currency (``Currency.decimals``), so a
    fiat-shaped asset at 2 decimals and a satoshi-scale asset at
    8 decimals get the right number of fractional digits.
    """
    value = Decimal("123.123456789")
    assert quantize_money(value, 2) == Decimal("123.12")
    assert quantize_money(value, 8) == Decimal("123.12345679")
    # Zero-decimal asset (rare, but supported) drops the fraction.
    assert quantize_money(value, 0) == Decimal("123")


def test_quantize_money_accepts_float_int_str_inputs() -> None:
    """The helper accepts the same inputs as ``to_decimal`` — every
    caller would otherwise have to remember the ``Decimal(str(...))``
    idiom by heart.
    """
    assert quantize_money(0.1, 2) == Decimal("0.10")
    assert quantize_money(0.2, 8) == Decimal("0.20000000")
    assert quantize_money(7, 2) == Decimal("7.00")
    assert quantize_money("0.12345678", 8) == Decimal("0.12345678")


@pytest.mark.parametrize(
    ("amount", "decimals", "expected"),
    [
        # 18-digit integer part — the upper edge of Numeric(28, 8).
        ("123456789012345678.12345678", 8, "123456789012345678.12345678"),
        # 12-digit integer part with 8 fractional digits — fits the
        # widened shape, would have overflowed Numeric(18, 8) pre-H-2.
        ("123456789012.34567890", 8, "123456789012.34567890"),
        # Pure-fraction input → keeps 8 satoshi digits.
        ("0.00000001", 8, "0.00000001"),
    ],
)
def test_quantize_money_round_trips_decimal_28_8(amount: str, decimals: int, expected: str) -> None:
    """Values at the upper edge of ``Numeric(28, 8)`` round-trip
    exactly — no truncation, no float drift.
    """
    assert quantize_money(Decimal(amount), decimals) == Decimal(expected)
