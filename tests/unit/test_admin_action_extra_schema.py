from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from backend.app.schemas import (
    Admin2faConfirmIn,
    Admin2faVerifyIn,
    AdminBroadcastCreateIn,
    AdminCategoryUpsertIn,
    AdminCommentUpdateIn,
    AdminCurrencyUpsertIn,
    AdminDealAssignArbiterIn,
    AdminDealForceOut,
    AdminDealSplitIn,
    AdminReasonIn,
    AdminReviewUpsertIn,
    AdminServiceUpdateIn,
    AdminSetRatingIn,
    AdminSetRoleIn,
    ServiceModerationDecision,
)

ADMIN_ACTION_SCHEMAS: list[tuple[type[BaseModel], dict[str, object]]] = [
    (ServiceModerationDecision, {"action": "ban"}),
    (AdminReasonIn, {}),
    (AdminSetRoleIn, {"is_vip": True}),
    (AdminSetRatingIn, {"rating": 4.7}),
    (AdminDealForceOut, {}),
    (AdminDealSplitIn, {"buyer_percent": 50}),
    (AdminDealAssignArbiterIn, {"arbiter_id": None}),
    (AdminServiceUpdateIn, {"title": "Updated"}),
    (AdminReviewUpsertIn, {"rating": 5, "text": ""}),
    (AdminCommentUpdateIn, {"text": "Updated"}),
    (AdminCategoryUpsertIn, {"slug": "cards", "name": "Cards"}),
    (AdminCurrencyUpsertIn, {"code": "USDT"}),
    (AdminBroadcastCreateIn, {"body": "Hello"}),
    (
        Admin2faConfirmIn,
        {"secret": "JBSWY3DPEHPK3PXP", "code": "123456"},
    ),
    (Admin2faVerifyIn, {"code": "123456"}),
]


@pytest.mark.parametrize("model,payload", ADMIN_ACTION_SCHEMAS)
def test_admin_action_schemas_reject_unknown_fields(
    model: type[BaseModel],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError) as exc:
        model(**payload, stale_field=1)

    error = exc.value.errors()[0]
    assert error["loc"] == ("stale_field",)
    assert error["type"] == "extra_forbidden"


@pytest.mark.parametrize("model,_payload", ADMIN_ACTION_SCHEMAS)
def test_admin_action_openapi_forbids_additional_properties(
    model: type[BaseModel],
    _payload: dict[str, object],
) -> None:
    assert model.model_json_schema()["additionalProperties"] is False
