from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.schemas import (
    AdminDealAssignArbiterIn,
    AdminDealForceOut,
    AdminDealSplitIn,
)


def test_admin_deal_action_ids_accept_positive_integer_or_none() -> None:
    assert AdminDealForceOut(approval_id=7).approval_id == 7
    assert AdminDealForceOut(approval_id=None).approval_id is None
    assert AdminDealSplitIn(buyer_percent=50, approval_id=8).approval_id == 8
    assert AdminDealSplitIn(buyer_percent=50, approval_id=None).approval_id is None
    assert AdminDealAssignArbiterIn(arbiter_id=9).arbiter_id == 9
    assert AdminDealAssignArbiterIn(arbiter_id=None).arbiter_id is None


@pytest.mark.parametrize("bad", [True, False, "1", 1.0, 0, -1])
def test_admin_deal_force_rejects_coerced_or_non_positive_approval_id(
    bad: object,
) -> None:
    with pytest.raises(ValidationError):
        AdminDealForceOut(approval_id=bad)


@pytest.mark.parametrize("bad", [True, False, "1", 1.0, 0, -1])
def test_admin_deal_split_rejects_coerced_or_non_positive_approval_id(
    bad: object,
) -> None:
    with pytest.raises(ValidationError):
        AdminDealSplitIn(buyer_percent=50, approval_id=bad)


@pytest.mark.parametrize("bad", [True, False, "1", 1.0, 0, -1])
def test_admin_deal_assign_arbiter_rejects_coerced_or_non_positive_arbiter_id(
    bad: object,
) -> None:
    with pytest.raises(ValidationError):
        AdminDealAssignArbiterIn(arbiter_id=bad)
