from __future__ import annotations

from decimal import Decimal

from backend.app.models import Deal, DealStatus
from backend.app.routers.deals import _deal_out
from backend.app.schemas import DealOut


def _deal() -> Deal:
    return Deal(
        id=1,
        buyer_id=10,
        seller_id=20,
        status=DealStatus.in_progress,
        amount=Decimal("1"),
        description="test deal",
        confirm_buyer=True,
        confirm_seller=True,
    )


def test_deal_out_projects_staff_viewer_as_other_role() -> None:
    deal = _deal()

    assert _deal_out(deal, 10).role == "buyer"
    assert _deal_out(deal, 20).role == "seller"
    assert _deal_out(deal, 30).role == "other"


def test_deal_out_role_contract_includes_staff_other_role() -> None:
    role_schema = DealOut.model_json_schema()["properties"]["role"]

    assert role_schema["enum"] == ["buyer", "seller", "other"]
