from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.app.schemas import AdminSettingsUpdateIn


def test_regular_commission_rejects_minus_one_before_db_constraint():
    """Only VIP commission uses -1 as the inherited-rate sentinel."""
    with pytest.raises(ValidationError) as exc:
        AdminSettingsUpdateIn(deal_commission_percent=Decimal("-1"))

    assert exc.value.errors()[0]["loc"] == ("deal_commission_percent",)


def test_regular_commission_accepts_zero_boundary():
    model = AdminSettingsUpdateIn(deal_commission_percent=Decimal("0"))

    assert model.deal_commission_percent == Decimal("0.00")


def test_vip_commission_keeps_minus_one_sentinel():
    model = AdminSettingsUpdateIn(vip_commission_percent=Decimal("-1"))

    assert model.vip_commission_percent == Decimal("-1.00")


def test_vip_commission_rejects_below_sentinel():
    with pytest.raises(ValidationError) as exc:
        AdminSettingsUpdateIn(vip_commission_percent=Decimal("-1.01"))

    assert exc.value.errors()[0]["loc"] == ("vip_commission_percent",)
