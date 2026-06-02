from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.schemas import (
    MAX_CURRENCY_CODE_LEN,
    WalletDepositCreateReq,
    WalletWithdrawCreateReq,
)


@pytest.mark.parametrize("model", [WalletDepositCreateReq, WalletWithdrawCreateReq])
def test_wallet_currency_code_is_trimmed_and_uppercased(model: type) -> None:
    body = model(currency_code=" usdt ", amount=1)

    assert body.currency_code == "USDT"


@pytest.mark.parametrize("model", [WalletDepositCreateReq, WalletWithdrawCreateReq])
@pytest.mark.parametrize(
    "bad",
    ["", "   ", "USD T", "USD-T", "юsd", "X" * (MAX_CURRENCY_CODE_LEN + 1)],
)
def test_wallet_currency_code_rejects_invalid_values(model: type, bad: str) -> None:
    with pytest.raises(ValidationError):
        model(currency_code=bad, amount=1)
