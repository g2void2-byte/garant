from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.schemas import AdminBroadcastCreateIn


def test_admin_broadcast_audience_ints_accept_explicit_ints_or_none() -> None:
    body = AdminBroadcastCreateIn(
        body="message",
        audience_active_days=7,
        audience_min_deals=0,
    )

    assert body.audience_active_days == 7
    assert body.audience_min_deals == 0
    assert AdminBroadcastCreateIn(body="message").audience_active_days is None


@pytest.mark.parametrize("field", ["audience_active_days", "audience_min_deals"])
@pytest.mark.parametrize("bad", [True, False, "5", 5.0, -1])
def test_admin_broadcast_audience_ints_reject_coerced_or_negative_values(
    field: str,
    bad: object,
) -> None:
    with pytest.raises(ValidationError):
        AdminBroadcastCreateIn(body="message", **{field: bad})
