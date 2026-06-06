from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from backend.app.schemas import (
    AdminCurrencyRateUpsertIn,
    AdminSettingsUpdateIn,
    AdminSetTrustDepositIn,
    AdminWalletAdjustIn,
    AdminWithdrawalDecisionIn,
)


@pytest.mark.parametrize(
    "model,payload",
    [
        (AdminSetTrustDepositIn, {"amount": 1}),
        (AdminWalletAdjustIn, {"currency_code": "USDT", "amount": 1}),
        (AdminCurrencyRateUpsertIn, {"currency_code": "USDT", "usd_rate": 1}),
        (AdminWithdrawalDecisionIn, {"action": "approve"}),
        (AdminSettingsUpdateIn, {"pin_reset_price_usd": 1}),
    ],
)
def test_financial_admin_write_schemas_reject_unknown_fields(
    model: type[BaseModel],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError) as exc:
        model(**payload, stale_field=1)

    error = exc.value.errors()[0]
    assert error["loc"] == ("stale_field",)
    assert error["type"] == "extra_forbidden"


@pytest.mark.parametrize(
    "model",
    [
        AdminSetTrustDepositIn,
        AdminWalletAdjustIn,
        AdminCurrencyRateUpsertIn,
        AdminWithdrawalDecisionIn,
        AdminSettingsUpdateIn,
    ],
)
def test_financial_admin_write_openapi_forbids_additional_properties(
    model: type[BaseModel],
) -> None:
    assert model.model_json_schema()["additionalProperties"] is False
