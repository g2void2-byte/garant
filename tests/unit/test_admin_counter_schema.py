from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.schemas import AdminServiceUpdateIn, AdminSetStatsIn, AdminSettingsUpdateIn


def test_admin_counter_fields_accept_explicit_non_negative_ints() -> None:
    stats = AdminSetStatsIn(deals_total=0, deals_success=1, good=2)
    service = AdminServiceUpdateIn(views=0, deals_count=3)
    settings = AdminSettingsUpdateIn(
        max_active_services_per_user=1,
        pending_topup_expiry_hours=0,
        faq_stats_users=10,
        faq_stats_deals=20,
    )

    assert stats.deals_total == 0
    assert stats.deals_success == 1
    assert stats.good == 2
    assert service.views == 0
    assert service.deals_count == 3
    assert settings.max_active_services_per_user == 1
    assert settings.pending_topup_expiry_hours == 0
    assert settings.faq_stats_users == 10
    assert settings.faq_stats_deals == 20


def test_admin_set_stats_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        AdminSetStatsIn(deposit_total=100)


@pytest.mark.parametrize(
    "field",
    ["deals_total", "deals_success", "deals_failed", "deals_arbitrage", "good", "bad"],
)
@pytest.mark.parametrize("bad", [True, False, "5", 1.0, -1])
def test_admin_set_stats_rejects_coerced_or_negative_ints(field: str, bad: object) -> None:
    with pytest.raises(ValidationError):
        AdminSetStatsIn(**{field: bad})


@pytest.mark.parametrize("field", ["views", "deals_count"])
@pytest.mark.parametrize("bad", [True, False, "5", 1.0, -1])
def test_admin_service_update_rejects_coerced_or_negative_counter_ints(
    field: str,
    bad: object,
) -> None:
    with pytest.raises(ValidationError):
        AdminServiceUpdateIn(**{field: bad})


@pytest.mark.parametrize(
    "field",
    ["title", "description", "price", "deposit", "views", "deals_count", "status"],
)
def test_admin_service_update_rejects_noop_explicit_null_fields(field: str) -> None:
    with pytest.raises(ValidationError) as exc:
        AdminServiceUpdateIn(**{field: None})

    assert exc.value.errors()[0]["loc"] == (field,)


def test_admin_service_update_accepts_nullable_rating_and_ban_reason_clears() -> None:
    body = AdminServiceUpdateIn(rating_manual=None, ban_reason=None)

    assert body.rating_manual is None
    assert body.ban_reason is None
    assert body.model_fields_set == {"rating_manual", "ban_reason"}


@pytest.mark.parametrize(
    "field",
    [
        "inactivity_pending_confirmation_days",
        "inactivity_pending_cancellation_days",
        "max_active_services_per_user",
        "pending_topup_expiry_hours",
        "faq_stats_users",
        "faq_stats_deals",
    ],
)
@pytest.mark.parametrize("bad", [True, False, "5", 1.0, -1])
def test_admin_settings_rejects_coerced_or_negative_ints(field: str, bad: object) -> None:
    with pytest.raises(ValidationError):
        AdminSettingsUpdateIn(**{field: bad})
