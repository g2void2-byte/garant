"""Bot banner image composition.

The static banners (Поиск, Помощь) are served as plain files by ``sections.py``
via ``FSInputFile``. The Сделки and Профиль banners are dynamically overlaid
with the user's values on top of pre-rendered templates.

The templates already include the yellow ``$`` glyph and the row labels —
this module only draws the numeric/text values at fixed coordinates.
"""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_ASSETS = Path(__file__).parent / "assets"
_FONT_PATH = _ASSETS / "DejaVuSans-Bold.ttf"

# Match the template's yellow accent (sampled from the source PNG).
_YELLOW = "#F5CC1D"
_WHITE = "#FFFFFF"

# Coordinates were measured against the source templates. They are
# expressed in pixels relative to the template's native resolution
# (``deals.jpg`` = 1493×1053, ``profile.jpg`` = 1187×1325).
_DEALS_SUM_XY = (175, 465)
_DEALS_BUYS_XY = (105, 820)
_DEALS_SALES_XY = (810, 820)
_DEALS_SUM_SIZE = 108
_DEALS_COUNT_SIZE = 86
_DEALS_SUM_MAX_WIDTH = 1140  # top card right edge minus left margin

_PROFILE_USERNAME_XY = (90, 1180)
_PROFILE_DEPOSIT_XY = (905, 1210)
_PROFILE_USERNAME_SIZE = 56
_PROFILE_DEPOSIT_SIZE = 88
_PROFILE_USERNAME_MAX_WIDTH = 700
_PROFILE_DEPOSIT_MAX_WIDTH = 240


@lru_cache(maxsize=16)
def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_FONT_PATH), size)


def _fmt_money(value: float) -> str:
    """``1234.5`` → ``"1 234.50"``, ``1234.0`` → ``"1 234"``."""
    if value == int(value):
        return f"{int(value):,}".replace(",", " ")
    return f"{value:,.2f}".replace(",", " ")


def _autofit(
    draw: ImageDraw.ImageDraw, text: str, base_size: int, max_width: int
) -> ImageFont.FreeTypeFont:
    """Pick the largest font ≤ ``base_size`` so ``text`` fits in ``max_width``."""
    size = base_size
    while size >= 24:
        font = _font(size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 4
    return _font(24)


def render_deals(*, total_volume: float, deal_count: int, sale_count: int) -> bytes:
    img = Image.open(_ASSETS / "deals.jpg").convert("RGB")
    draw = ImageDraw.Draw(img)
    sum_text = _fmt_money(total_volume)
    draw.text(
        _DEALS_SUM_XY,
        sum_text,
        fill=_YELLOW,
        font=_autofit(draw, sum_text, _DEALS_SUM_SIZE, _DEALS_SUM_MAX_WIDTH),
    )
    draw.text(
        _DEALS_BUYS_XY,
        str(deal_count),
        fill=_WHITE,
        font=_font(_DEALS_COUNT_SIZE),
    )
    draw.text(
        _DEALS_SALES_XY,
        str(sale_count),
        fill=_WHITE,
        font=_font(_DEALS_COUNT_SIZE),
    )
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()


def render_profile(*, username: str | None, deposit: float) -> bytes:
    img = Image.open(_ASSETS / "profile.jpg").convert("RGB")
    draw = ImageDraw.Draw(img)
    label = f"@{username}" if username else "—"
    draw.text(
        _PROFILE_USERNAME_XY,
        label,
        fill=_WHITE,
        font=_autofit(draw, label, _PROFILE_USERNAME_SIZE, _PROFILE_USERNAME_MAX_WIDTH),
    )
    deposit_text = _fmt_money(deposit)
    draw.text(
        _PROFILE_DEPOSIT_XY,
        deposit_text,
        fill=_YELLOW,
        font=_autofit(draw, deposit_text, _PROFILE_DEPOSIT_SIZE, _PROFILE_DEPOSIT_MAX_WIDTH),
    )
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()
