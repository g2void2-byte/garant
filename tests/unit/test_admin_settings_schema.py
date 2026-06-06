from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.app.schemas import AdminSettingsUpdateIn

SETTINGS_UPDATE_FIELDS = [
    "deal_commission_percent",
    "vip_commission_percent",
    "inactivity_pending_confirmation_days",
    "inactivity_pending_cancellation_days",
    "max_active_services_per_user",
    "maintenance_enabled",
    "maintenance_message",
    "auto_withdraw_enabled",
    "pending_topup_expiry_hours",
    "pin_reset_price_usd",
    "faq_stats_badge_enabled",
    "faq_stats_users",
    "faq_stats_deals",
    "faq_stats_total_usd",
]


@pytest.mark.parametrize("field", SETTINGS_UPDATE_FIELDS)
def test_settings_update_rejects_explicit_null(field: str):
    with pytest.raises(ValidationError) as exc:
        AdminSettingsUpdateIn(**{field: None})

    assert exc.value.errors()[0]["loc"] == (field,)


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


@pytest.mark.parametrize("field", ["faq_stats_users", "faq_stats_deals"])
def test_faq_stats_counts_reject_negative_values(field: str):
    with pytest.raises(ValidationError) as exc:
        AdminSettingsUpdateIn(**{field: -1})

    assert exc.value.errors()[0]["loc"] == (field,)


def test_faq_stats_total_usd_rejects_negative_value():
    with pytest.raises(ValidationError) as exc:
        AdminSettingsUpdateIn(faq_stats_total_usd=Decimal("-0.01"))

    assert exc.value.errors()[0]["loc"] == ("faq_stats_total_usd",)


def test_faq_stats_values_accept_zero_boundary():
    model = AdminSettingsUpdateIn(
        faq_stats_users=0,
        faq_stats_deals=0,
        faq_stats_total_usd=Decimal("0"),
    )

    assert model.faq_stats_users == 0
    assert model.faq_stats_deals == 0
    assert model.faq_stats_total_usd == Decimal("0")


@pytest.mark.parametrize("value", [Decimal("Infinity"), Decimal("NaN")])
def test_pin_reset_price_rejects_non_finite_values(value: Decimal):
    with pytest.raises(ValidationError) as exc:
        AdminSettingsUpdateIn(pin_reset_price_usd=value)

    assert exc.value.errors()[0]["loc"][0] == "pin_reset_price_usd"
