from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from backend.app.routers.client_errors import ClientErrorReport
from backend.app.schemas import ServiceCreate, ServiceUpdate, UserUpdate

OPEN_PROFILE_SERVICE_SCHEMAS: list[tuple[type[BaseModel], dict[str, object]]] = [
    (ClientErrorReport, {"message": "boom"}),
    (ServiceCreate, {"category_slug": "services", "title": "Title"}),
    (ServiceUpdate, {"title": "Title"}),
    (UserUpdate, {"display_name": "alice"}),
]


@pytest.mark.parametrize("model,payload", OPEN_PROFILE_SERVICE_SCHEMAS)
def test_profile_service_schemas_accept_valid_payloads(
    model: type[BaseModel],
    payload: dict[str, object],
) -> None:
    model(**payload)


@pytest.mark.parametrize("model,payload", OPEN_PROFILE_SERVICE_SCHEMAS)
def test_profile_service_schemas_reject_unknown_fields(
    model: type[BaseModel],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError) as exc:
        model(**payload, stale_field=1)

    error = exc.value.errors()[0]
    assert error["loc"] == ("stale_field",)
    assert error["type"] == "extra_forbidden"


@pytest.mark.parametrize("model,_payload", OPEN_PROFILE_SERVICE_SCHEMAS)
def test_profile_service_openapi_forbids_additional_properties(
    model: type[BaseModel],
    _payload: dict[str, object],
) -> None:
    assert model.model_json_schema()["additionalProperties"] is False
