"""Canonical money helpers — H-2 contract.

H-2 unified every per-currency money column in the schema to
``Numeric(MONEY_PRECISION, MONEY_SCALE)`` (``Numeric(28, 8)``). Before
the unification two parallel inconsistencies leaked into responses
and ledger writes:

1. Four money columns lagged at ``Numeric(14, 2)`` —
   ``Service.price``, ``Service.deposit``, ``AppSettings.min_deposit`` and
   ``AppSettings.min_withdraw``. Writing a satoshi-scale value (8 fractional
   digits) into those columns silently truncated the trailing six digits.
   The companion migration widens all four to ``Numeric(28, 8)``.
2. Two near-identical ``_q`` helpers lived in
   ``services_deals.py`` and ``routers/admin/deals.py``. Both quantised via
   ``Decimal.quantize`` without an explicit ``rounding`` keyword, inheriting
   whatever rounding mode the current ``decimal`` context happened to have.
   Python defaults to ``ROUND_HALF_EVEN`` so the behaviour was correct in
   practice, but the contract was implicit. A future caller flipping the
   thread-local context (``decimal.getcontext().rounding = ROUND_HALF_UP``)
   would have silently re-rounded every money figure.

This module centralises both concerns:

* ``MONEY_PRECISION`` / ``MONEY_SCALE`` — the single source of truth for the
  canonical ``Numeric(28, 8)`` shape. Used by the migration, by the model
  ``mapped_column(Numeric(...))`` declarations, and by tests that assert
  the database/ORM stays in sync.
* ``MONEY_ROUNDING`` — ``ROUND_HALF_EVEN`` (banker's rounding). Pinned here
  so the contract is explicit and a future audit can grep for the symbol
  to find every quantisation site.
* ``quantize_money(value, decimals)`` — the only blessed way to quantise a
  money figure for output. Accepts ``Decimal`` / ``float`` / ``int`` /
  ``str`` and routes through ``Decimal(str(value))`` so ``float``
  representational noise (``Decimal(0.1) != Decimal('0.1')``) never leaks
  into a stored / serialised value. Always passes ``rounding=ROUND_HALF_EVEN``.
* ``to_decimal(value)`` — the safe ``Decimal`` coercion used elsewhere in
  the codebase, factored out so callers don't have to remember the
  ``Decimal(str(value))`` idiom by heart.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

# ── Canonical Numeric shape ────────────────────────────────────────────
#
# Every per-currency money column in the schema declares
# ``mapped_column(Numeric(MONEY_PRECISION, MONEY_SCALE))``. The H-2
# migration widened the last five lagging columns to match. Tests in
# ``tests/test_h2_money_precision_widening.py`` round-trip a value at
# the upper bound of this shape (18-digit integer part, 8 fractional
# digits) for every column to keep the contract pinned at the DB level.
MONEY_PRECISION: int = 28
MONEY_SCALE: int = 8

# Banker's rounding (ROUND_HALF_EVEN) — pinned explicitly because
# ``Decimal.quantize`` otherwise reads the thread-local
# ``decimal.getcontext().rounding`` mode. The default happens to be
# ROUND_HALF_EVEN today, but the contract here is that money output is
# always banker's-rounded regardless of any context the caller may have
# set on its own thread.
MONEY_ROUNDING: str = ROUND_HALF_EVEN


def to_decimal(value: Decimal | float | int | str) -> Decimal:
    """Coerce ``value`` to ``Decimal`` without picking up float noise.

    ``Decimal(0.1)`` constructs ``Decimal('0.1000000000000000055511151231...')``
    because ``0.1`` has no exact binary representation. The codebase
    sidesteps the issue by routing through ``str`` first
    (``Decimal(str(0.1)) == Decimal('0.1')``). This helper makes the
    idiom explicit so every site that touches a money figure does the
    same thing.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize_money(value: Decimal | float | int | str, decimals: int) -> Decimal:
    """Quantise ``value`` to ``decimals`` fractional digits using
    ``ROUND_HALF_EVEN``.

    ``decimals`` is the per-currency precision (``Currency.decimals``);
    a USDT amount is quantised to 8 digits, a fiat-shaped asset with
    ``decimals=2`` is quantised to 2.  This matches the way the rest
    of the codebase quantises against the currency record rather than
    a global constant.
    """
    quant = Decimal(10) ** -decimals
    return to_decimal(value).quantize(quant, rounding=MONEY_ROUNDING)
