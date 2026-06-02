from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.schemas import AdminCommentUpdateIn, ServiceCommentCreate


def test_service_comment_create_accepts_integer_rating_or_none() -> None:
    assert ServiceCommentCreate(text="ok", rating=5).rating == 5
    assert ServiceCommentCreate(text="ok", rating=None).rating is None


@pytest.mark.parametrize("bad", [True, False, "5", 1.0, 0, 6])
def test_service_comment_create_rejects_coerced_or_out_of_range_rating(
    bad: object,
) -> None:
    with pytest.raises(ValidationError):
        ServiceCommentCreate(text="ok", rating=bad)


def test_admin_comment_update_accepts_integer_rating_or_none() -> None:
    assert AdminCommentUpdateIn(rating=5).rating == 5
    assert AdminCommentUpdateIn(rating=None).rating is None


@pytest.mark.parametrize("bad", [True, False, "5", 1.0, 0, 6])
def test_admin_comment_update_rejects_coerced_or_out_of_range_rating(
    bad: object,
) -> None:
    with pytest.raises(ValidationError):
        AdminCommentUpdateIn(rating=bad)
