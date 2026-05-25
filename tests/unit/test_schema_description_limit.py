"""Description-length regression for user-supplied public schemas.

The admin-side ``AdminServiceUpdateIn._description_ok`` has carried a
4000-character cap for some time, but the public-facing
``ServiceCreate`` / ``ServiceUpdate`` / ``DealCreate`` schemas accepted
unbounded payloads — predictable bloat for the FTS pipeline and the
admin-panel text views. These tests pin the user-side limit to the
same 4000-character invariant.

Each test exercises both the boundary (``MAX_DESCRIPTION_LEN``
characters — accepted) and one-over-boundary (``MAX_DESCRIPTION_LEN +
1`` — rejected). ``ServiceUpdate`` additionally verifies that ``None``
("don't touch") still passes through.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.schemas import (
    MAX_DESCRIPTION_LEN,
    DealCreate,
    ServiceCreate,
    ServiceUpdate,
)


def test_service_create_accepts_description_at_limit():
    body = "x" * MAX_DESCRIPTION_LEN
    model = ServiceCreate(category_slug="misc", title="t", description=body)
    assert model.description == body


def test_service_create_rejects_description_over_limit():
    body = "x" * (MAX_DESCRIPTION_LEN + 1)
    with pytest.raises(ValidationError) as exc:
        ServiceCreate(category_slug="misc", title="t", description=body)
    assert "Описание слишком длинное" in str(exc.value)


def test_service_update_accepts_description_at_limit():
    body = "y" * MAX_DESCRIPTION_LEN
    model = ServiceUpdate(description=body)
    assert model.description == body


def test_service_update_rejects_description_over_limit():
    body = "y" * (MAX_DESCRIPTION_LEN + 1)
    with pytest.raises(ValidationError) as exc:
        ServiceUpdate(description=body)
    assert "Описание слишком длинное" in str(exc.value)


def test_service_update_allows_none_description():
    """``ServiceUpdate`` is a PATCH-style schema — ``None`` means
    "don't touch this field" and must round-trip unchanged.
    """
    model = ServiceUpdate(description=None)
    assert model.description is None


def test_deal_create_accepts_description_at_limit():
    body = "z" * MAX_DESCRIPTION_LEN
    model = DealCreate(
        counterparty="bob",
        role="buyer",
        amount=1.0,
        description=body,
    )
    assert model.description == body


def test_deal_create_rejects_description_over_limit():
    body = "z" * (MAX_DESCRIPTION_LEN + 1)
    with pytest.raises(ValidationError) as exc:
        DealCreate(
            counterparty="bob",
            role="buyer",
            amount=1.0,
            description=body,
        )
    assert "Описание слишком длинное" in str(exc.value)
