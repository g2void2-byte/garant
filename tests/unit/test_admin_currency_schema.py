from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.schemas import (
    MAX_CURRENCY_CODE_LEN,
    AdminCurrencyRateUpsertIn,
    AdminCurrencyUpsertIn,
    AdminWalletAdjustIn,
)


@pytest.mark.parametrize(
    "model,kwargs,field",
    [
        (AdminCurrencyUpsertIn, {}, "code"),
        (AdminWalletAdjustIn, {"amount": 1}, "currency_code"),
        (AdminCurrencyRateUpsertIn, {"usd_rate": 1}, "currency_code"),
    ],
)
def test_admin_currency_code_fields_trim_and_uppercase(
    model: type,
    kwargs: dict[str, object],
    field: str,
) -> None:
    body = model(**{field: " usdt ", **kwargs})

    assert getattr(body, field) == "USDT"


@pytest.mark.parametrize(
    "model,kwargs,field",
    [
        (AdminCurrencyUpsertIn, {}, "code"),
        (AdminWalletAdjustIn, {"amount": 1}, "currency_code"),
        (AdminCurrencyRateUpsertIn, {"usd_rate": 1}, "currency_code"),
    ],
)
@pytest.mark.parametrize(
    "bad",
    ["", "   ", "USD T", "USD-T", "\u044esd", "X" * (MAX_CURRENCY_CODE_LEN + 1)],
)
def test_admin_currency_code_fields_reject_invalid_values(
    model: type,
    kwargs: dict[str, object],
    field: str,
    bad: str,
) -> None:
    with pytest.raises(ValidationError):
        model(**{field: bad, **kwargs})


def test_admin_currency_integer_fields_accept_explicit_ints_or_none() -> None:
    currency = AdminCurrencyUpsertIn(code="USD", decimals=8, sort_order=7)

    assert currency.decimals == 8
    assert currency.sort_order == 7
    assert AdminCurrencyUpsertIn(code="USD", decimals=None, sort_order=None).decimals is None


@pytest.mark.parametrize("bad", [True, False, "8", 8.0, -1, 9, 18, 19])
def test_admin_currency_decimals_rejects_coerced_or_out_of_range_ints(
    bad: object,
) -> None:
    with pytest.raises(ValidationError):
        AdminCurrencyUpsertIn(code="USD", decimals=bad)


@pytest.mark.parametrize("bad", [True, False, "7", 7.0])
def test_admin_currency_sort_order_rejects_coerced_ints(bad: object) -> None:
    with pytest.raises(ValidationError):
        AdminCurrencyUpsertIn(code="USD", sort_order=bad)


def test_admin_currency_text_fields_are_trimmed_and_bounded() -> None:
    currency = AdminCurrencyUpsertIn(
        code="USD",
        name=" US Dollar ",
        network=" TRC20 ",
        icon_url="https://example.com/usd.png",
    )

    assert currency.name == "US Dollar"
    assert currency.network == "TRC20"
    assert currency.icon_url == "https://example.com/usd.png"


@pytest.mark.parametrize(
    "field,bad",
    [
        ("name", "   "),
        ("name", "A" * 65),
        ("network", "N" * 33),
        ("icon_url", "http://example.com/usd.png"),
        ("icon_url", "https:///usd.png"),
        ("icon_url", "https://example.com/" + "a" * 1025),
    ],
)
def test_admin_currency_text_fields_reject_invalid_values(field: str, bad: str) -> None:
    with pytest.raises(ValidationError):
        AdminCurrencyUpsertIn(code="USD", **{field: bad})
