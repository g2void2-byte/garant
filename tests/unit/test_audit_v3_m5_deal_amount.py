"""Audit v3 M-5 — schema-layer validation of ``DealCreate.amount``.

Pre-fix the field used ``Field(gt=0)`` which accepted absurd values
that quantised to zero downstream (``Decimal("1e-20")`` on an
8-decimal asset → ``Decimal("0E-8")``).  The schema-layer guard
in this PR is ``Field(ge=Decimal("0.00000001"))`` plus an explicit
``_reject_non_finite_money`` validator to catch ``NaN`` / ``±inf``
(which Pydantic's bound comparison would otherwise admit because
``NaN`` comparisons return ``False`` against any number).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.app.schemas import DealCreate


def _ok(amount):
    return DealCreate(counterparty="bob", role="buyer", amount=amount)


def test_deal_create_accepts_one_satoshi() -> None:
    """``1e-8`` is the smallest representable amount our money
    columns (``Numeric(28, 8)``) can store; the schema accepts it."""
    model = _ok(Decimal("0.00000001"))
    assert model.amount == Decimal("0.00000001")


def test_deal_create_accepts_typical_amount() -> None:
    model = _ok(Decimal("12.34"))
    assert model.amount == Decimal("12.34")


@pytest.mark.parametrize(
    "bad_amount",
    [
        Decimal("0"),
        Decimal("-0.00000001"),
        Decimal("-1"),
        # Sub-satoshi positive value — quantises to 0 downstream so
        # the schema must reject it before ``create_deal`` ever locks
        # the buyer balance.
        Decimal("0.000000001"),
        Decimal("1e-20"),
    ],
)
def test_deal_create_rejects_zero_or_subsatoshi(bad_amount) -> None:
    with pytest.raises(ValidationError):
        _ok(bad_amount)


@pytest.mark.parametrize(
    "bad_amount",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_deal_create_rejects_non_finite(bad_amount) -> None:
    """``NaN``/``±inf`` slip through ``Field(ge=...)`` because every
    comparison against ``NaN`` returns ``False``; the dedicated
    ``_reject_non_finite_money`` validator catches them."""
    with pytest.raises(ValidationError):
        _ok(bad_amount)
