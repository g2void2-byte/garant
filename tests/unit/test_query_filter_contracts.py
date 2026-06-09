from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

import pytest
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from backend.app.schemas import (
    CURRENCY_CODE_PATTERN,
    MAX_CURRENCY_CODE_LEN,
    CurrencyCodeStr,
)


def test_currency_code_query_type_trims_and_uppercases() -> None:
    assert TypeAdapter(CurrencyCodeStr).validate_python(" usdt ") == "USDT"


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "USD T", "USD-T", "юsd", "X" * (MAX_CURRENCY_CODE_LEN + 1)],
)
def test_currency_code_query_type_rejects_invalid_values(bad: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(CurrencyCodeStr).validate_python(bad)


def _query_contract_client() -> TestClient:
    app = FastAPI()

    @app.get("/filters")
    def filters(
        status: Annotated[Literal["any", "pending"], Query()] = "any",
        currency: Annotated[
            CurrencyCodeStr | None,
            Query(description="Optional currency code filter."),
        ] = None,
        min_amount: Annotated[Decimal | None, Query(ge=0)] = None,
        user_id: Annotated[int | None, Query(ge=1)] = None,
    ) -> dict[str, str | None]:
        return {
            "status": status,
            "currency": currency,
            "min_amount": str(min_amount) if min_amount is not None else None,
            "user_id": str(user_id) if user_id is not None else None,
        }

    return TestClient(app)


def test_fastapi_query_contract_normalizes_currency_and_keeps_openapi_bounds() -> None:
    client = _query_contract_client()

    response = client.get(
        "/filters",
        params={"status": "pending", "currency": " usdt ", "min_amount": "1.25", "user_id": "7"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "pending",
        "currency": "USDT",
        "min_amount": "1.25",
        "user_id": "7",
    }

    parameters = {
        item["name"]: item
        for item in client.get("/openapi.json").json()["paths"]["/filters"]["get"]["parameters"]
    }
    currency_schema = parameters["currency"]["schema"]["anyOf"][0]
    assert currency_schema["maxLength"] == MAX_CURRENCY_CODE_LEN
    assert currency_schema["pattern"] == CURRENCY_CODE_PATTERN
    assert parameters["status"]["schema"]["enum"] == ["any", "pending"]
    assert parameters["min_amount"]["schema"]["anyOf"][0]["minimum"] == 0.0
    assert parameters["user_id"]["schema"]["anyOf"][0]["minimum"] == 1


@pytest.mark.parametrize(
    "params",
    [
        {"status": "bogus"},
        {"currency": "USD-T"},
        {"currency": "юsd"},
        {"min_amount": "-1"},
        {"min_amount": "NaN"},
        {"min_amount": "Infinity"},
        {"user_id": "0"},
    ],
)
def test_fastapi_query_contract_rejects_malformed_filters(params: dict[str, str]) -> None:
    response = _query_contract_client().get("/filters", params=params)

    assert response.status_code == 422
