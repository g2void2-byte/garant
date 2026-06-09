from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.schemas import MAX_USERNAME_REF_LEN, ReviewCreate


def test_review_create_accepts_explicit_positive_integer_fields() -> None:
    model = ReviewCreate(target_username="target", rating=5, deal_id=42)

    assert model.rating == 5
    assert model.deal_id == 42


def test_review_create_normalizes_target_username() -> None:
    model = ReviewCreate(target_username="  @target-user_1  ", rating=5, deal_id=42)

    assert model.target_username == "target-user_1"


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "@", "bad user", "юзер", "x" * (MAX_USERNAME_REF_LEN + 1)],
)
def test_review_create_rejects_invalid_target_username(bad: str) -> None:
    with pytest.raises(ValidationError):
        ReviewCreate(target_username=bad, rating=5, deal_id=42)


@pytest.mark.parametrize("bad", [True, False, "5", 1.0, 0, 6])
def test_review_create_rejects_coerced_or_out_of_range_rating(bad: object) -> None:
    with pytest.raises(ValidationError):
        ReviewCreate(target_username="target", rating=bad, deal_id=42)


@pytest.mark.parametrize("bad", [True, False, "42", 42.0, 0, -1])
def test_review_create_rejects_coerced_or_non_positive_deal_id(bad: object) -> None:
    with pytest.raises(ValidationError):
        ReviewCreate(target_username="target", rating=5, deal_id=bad)
