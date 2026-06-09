from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.schemas import DealMessageCreate


def test_deal_message_attachments_accept_positive_integer_ids() -> None:
    model = DealMessageCreate(text="x", attachments=[1, 42])
    assert model.attachments == [1, 42]


@pytest.mark.parametrize("bad", [[True], [False], ["1"], [1.0], [0], [-1]])
def test_deal_message_attachments_reject_coerced_or_non_positive_ids(bad: list[object]) -> None:
    with pytest.raises(ValidationError):
        DealMessageCreate(text="x", attachments=bad)
