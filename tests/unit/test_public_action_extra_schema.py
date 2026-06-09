from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from backend.app.routers.account import TransferConfirmIn
from backend.app.routers.pin import PinChangeIn, PinCheckIn, PinResetConfirmIn, PinSetupIn
from backend.app.schemas import (
    DealArbitrationRequest,
    DealCancelRequest,
    DealCreate,
    DealCreateWithTopup,
    DealMessageCreate,
    DealResolveRequest,
    ReviewCreate,
    ServiceCommentCreate,
    WalletDepositCreateReq,
    WalletWithdrawCreateReq,
)

PUBLIC_ACTION_SCHEMAS: list[tuple[type[BaseModel], dict[str, object]]] = [
    (PinSetupIn, {"pin": "1234"}),
    (PinCheckIn, {"pin": "1234"}),
    (PinChangeIn, {"old_pin": "1234", "new_pin": "5678"}),
    (PinResetConfirmIn, {"code": "123456", "new_pin": "5678"}),
    (TransferConfirmIn, {"code": "123456"}),
    (WalletDepositCreateReq, {"currency_code": "USDT", "amount": 1}),
    (WalletWithdrawCreateReq, {"currency_code": "USDT", "amount": 1}),
    (DealCreate, {"counterparty": "seller", "amount": 1}),
    (DealCreateWithTopup, {"counterparty": "seller", "amount": 1}),
    (DealCancelRequest, {}),
    (DealArbitrationRequest, {}),
    (DealResolveRequest, {"winner": "buyer"}),
    (DealMessageCreate, {}),
    (ReviewCreate, {"target_username": "seller", "rating": 5, "deal_id": 1}),
    (ServiceCommentCreate, {}),
]


@pytest.mark.parametrize("model,payload", PUBLIC_ACTION_SCHEMAS)
def test_public_action_schemas_reject_unknown_fields(
    model: type[BaseModel],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError) as exc:
        model(**payload, stale_field=1)

    error = exc.value.errors()[0]
    assert error["loc"] == ("stale_field",)
    assert error["type"] == "extra_forbidden"


@pytest.mark.parametrize("model,_payload", PUBLIC_ACTION_SCHEMAS)
def test_public_action_openapi_forbids_additional_properties(
    model: type[BaseModel],
    _payload: dict[str, object],
) -> None:
    assert model.model_json_schema()["additionalProperties"] is False
