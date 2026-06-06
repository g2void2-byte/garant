from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from backend.app.schemas import (
    AdminBroadcastCreateIn,
    AdminCommentUpdateIn,
    AdminCurrencyUpsertIn,
    AdminServiceUpdateIn,
    AdminSetRoleIn,
    AdminSettingsUpdateIn,
    UserUpdate,
)

BAD_BOOL_VALUES: tuple[object, ...] = ("true", "false", 1, 0)


@pytest.mark.parametrize(
    "field",
    ["dm_deals", "dm_deposits", "dm_system", "is_anonymous_deals", "is_hidden_profile"],
)
def test_user_update_accepts_only_real_bool_or_none_for_flags(field: str) -> None:
    assert getattr(UserUpdate(**{field: True}), field) is True
    assert getattr(UserUpdate(**{field: False}), field) is False
    assert getattr(UserUpdate(**{field: None}), field) is None

    for bad in BAD_BOOL_VALUES:
        with pytest.raises(ValidationError):
            UserUpdate(**{field: bad})


@pytest.mark.parametrize("field", ["is_admin", "is_arbiter", "is_vip"])
def test_admin_role_flags_reject_coerced_bool_values(field: str) -> None:
    assert getattr(AdminSetRoleIn(**{field: True}), field) is True
    assert getattr(AdminSetRoleIn(**{field: False}), field) is False

    for bad in (*BAD_BOOL_VALUES, None):
        with pytest.raises(ValidationError):
            AdminSetRoleIn(**{field: bad})


@pytest.mark.parametrize("model", [AdminServiceUpdateIn, AdminCommentUpdateIn])
def test_clear_rating_rejects_coerced_bool_values(model: type[Any]) -> None:
    assert model(clear_rating=True).clear_rating is True
    assert model(clear_rating=False).clear_rating is False

    for bad in (*BAD_BOOL_VALUES, None):
        with pytest.raises(ValidationError):
            model(clear_rating=bad)


@pytest.mark.parametrize(
    "field",
    ["maintenance_enabled", "auto_withdraw_enabled", "faq_stats_badge_enabled"],
)
def test_admin_settings_accepts_only_real_bool_for_requested_flags(field: str) -> None:
    assert getattr(AdminSettingsUpdateIn(**{field: True}), field) is True
    assert getattr(AdminSettingsUpdateIn(**{field: False}), field) is False

    for bad in (*BAD_BOOL_VALUES, None):
        with pytest.raises(ValidationError):
            AdminSettingsUpdateIn(**{field: bad})


def test_admin_currency_is_active_rejects_coerced_bool_values() -> None:
    assert AdminCurrencyUpsertIn(code="USD", is_active=True).is_active is True
    assert AdminCurrencyUpsertIn(code="USD", is_active=False).is_active is False
    assert AdminCurrencyUpsertIn(code="USD", is_active=None).is_active is None

    for bad in BAD_BOOL_VALUES:
        with pytest.raises(ValidationError):
            AdminCurrencyUpsertIn(code="USD", is_active=bad)


@pytest.mark.parametrize("field", ["dispatch_inapp", "dispatch_dm"])
def test_admin_broadcast_dispatch_flags_reject_coerced_bool_values(field: str) -> None:
    other = "dispatch_dm" if field == "dispatch_inapp" else "dispatch_inapp"

    assert getattr(AdminBroadcastCreateIn(body="body", **{field: True}), field) is True
    body = AdminBroadcastCreateIn(body="body", **{field: False, other: True})
    assert getattr(body, field) is False

    for bad in (*BAD_BOOL_VALUES, None):
        with pytest.raises(ValidationError):
            AdminBroadcastCreateIn(body="body", **{field: bad, other: True})
