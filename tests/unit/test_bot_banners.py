"""Unit tests for the bot banner image composition.

We don't pixel-diff the rendered PNGs against a golden image — that's
brittle and font-version dependent. Instead we exercise the public
``render_*`` functions across a range of values and assert that the
output is a non-trivial JPEG byte stream the same size as the template.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from backend.app.bot import banners


@pytest.mark.parametrize(
    ("volume", "deals", "sales"),
    [
        (0.0, 0, 0),
        (42.5, 4, 2),
        (1_234_567.89, 152, 45),
    ],
)
def test_render_deals_produces_valid_jpeg(volume: float, deals: int, sales: int) -> None:
    data = banners.render_deals(total_volume=volume, deal_count=deals, sale_count=sales)
    assert len(data) > 5_000, "rendered image suspiciously small"
    img = Image.open(io.BytesIO(data))
    assert img.format == "JPEG"
    # Template native size is preserved.
    assert img.size == (1493, 1053)


@pytest.mark.parametrize(
    ("username", "deposit"),
    [
        ("ksenodsa", 0.0),
        ("alice", 12.5),
        ("verylongusernameindeed", 999_999.99),
        (None, 0.0),
    ],
)
def test_render_profile_produces_valid_jpeg(username: str | None, deposit: float) -> None:
    data = banners.render_profile(username=username, deposit=deposit)
    assert len(data) > 5_000
    img = Image.open(io.BytesIO(data))
    assert img.format == "JPEG"
    # V14 — template replaced with the EW Garant wooden-frame artwork
    # at 1254×1254 (was 1187×1325 for the Continental template).
    assert img.size == (1254, 1254)


def test_fmt_money_uses_thin_space_grouping() -> None:
    assert banners._fmt_money(0) == "0"
    assert banners._fmt_money(1) == "1"
    assert banners._fmt_money(1234) == "1 234"
    assert banners._fmt_money(1234567) == "1 234 567"
    assert banners._fmt_money(1234.56) == "1 234.56"


def test_autofit_returns_smaller_font_for_overflow() -> None:
    # Direct API check: width-bounded fitting must shrink for long strings.
    img = Image.new("RGB", (200, 200))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    big = banners._autofit(draw, "1 234 567.89", base_size=88, max_width=200)
    small = banners._autofit(draw, "0", base_size=88, max_width=200)
    assert big.size < small.size
