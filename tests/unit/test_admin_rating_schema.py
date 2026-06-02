from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from backend.app.schemas import AdminSetRatingIn

BAD_RATINGS: tuple[object, ...] = (True, False, "4.2", "NaN", math.nan, math.inf, -1, 6)


def test_admin_set_rating_accepts_explicit_finite_number_or_none() -> None:
    assert AdminSetRatingIn(rating=0).rating == 0
    assert AdminSetRatingIn(rating=4.8).rating == 4.8
    assert AdminSetRatingIn(rating=None).rating is None


@pytest.mark.parametrize("bad", BAD_RATINGS)
def test_admin_set_rating_rejects_coerced_non_finite_or_out_of_range_values(
    bad: object,
) -> None:
    with pytest.raises(ValidationError):
        AdminSetRatingIn(rating=bad)
