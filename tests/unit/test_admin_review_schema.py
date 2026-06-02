from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.schemas import AdminReviewUpsertIn


def test_admin_review_upsert_accepts_positive_integer_ids() -> None:
    model = AdminReviewUpsertIn(author_id=1, target_id=2, deal_id=3, rating=5)

    assert model.author_id == 1
    assert model.target_id == 2
    assert model.deal_id == 3


def test_admin_review_upsert_accepts_omitted_ids_for_edit() -> None:
    model = AdminReviewUpsertIn(rating=4, text="edited")

    assert model.author_id is None
    assert model.target_id is None
    assert model.deal_id is None


@pytest.mark.parametrize("field", ["author_id", "target_id", "deal_id"])
@pytest.mark.parametrize("bad", [True, False, "1", 1.0, 0, -1])
def test_admin_review_upsert_rejects_coerced_or_non_positive_ids(
    field: str,
    bad: object,
) -> None:
    with pytest.raises(ValidationError):
        AdminReviewUpsertIn(rating=5, **{field: bad})
