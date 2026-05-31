"""Bot banner image composition.

The static banners (Поиск, Помощь) are served as plain files by ``sections.py``
via ``FSInputFile``. The Сделки and Профиль banners are dynamically overlaid
with the user's values on top of pre-rendered templates.

The templates already include the yellow ``$`` glyph and the row labels —
this module only draws the numeric/text values at fixed coordinates.
"""

from __future__ import annotations

import io
import logging
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

logger = logging.getLogger(__name__)

_ASSETS = Path(__file__).parent / "assets"
_FONT_PATH = _ASSETS / "DejaVuSans-Bold.ttf"

# Match the template's yellow accent (sampled from the source PNG).
_YELLOW = "#F5CC1D"
_WHITE = "#FFFFFF"
_BLACK = "#000000"

# Coordinates were measured against the source templates. They are
# expressed in pixels relative to the template's native resolution
# (``deals.jpg`` = 1493×1053).
# Top card: "Сумма сделок" label is part of the template at the
# top-left (~y=85); the value sits directly underneath it. The
# template also carries a decorative yellow ``$`` glyph further down
# the card — we draw our own ``$`` together with the value here so
# the rendered number isn't 400px below its own label. Bottom-card
# values follow the same rhythm — right under the label, not at the
# bottom edge of the card.
_DEALS_SUM_XY = (110, 165)
_DEALS_BUYS_XY = (105, 870)
_DEALS_SALES_XY = (810, 870)
_DEALS_SUM_SIZE = 96
_DEALS_COUNT_SIZE = 86
_DEALS_SUM_MAX_WIDTH = 1300  # leave breathing room across the wide card

# The template ships with a decorative yellow ``$`` glyph at this
# bbox (left, top, right, bottom) — we now draw our own ``$`` above
# the card next to the value, so this leftover glyph would look like
# a duplicate. Paint it out with the card's background colour before
# any text rendering.
_DEALS_TEMPLATE_DOLLAR_BBOX = (95, 506, 170, 610)
_DEALS_CARD_BG = (38, 38, 38)

# Profile template (``profile-new.png`` = 1254×1254). The wooden
# frame's interior black panel is a slightly rotated quadrilateral
# (perspective-warped 3-D render). These four corners were measured
# by flood-filling the dark central region from a known interior
# seed point; the avatar is perspective-mapped onto this quad so it
# fills the frame exactly (no circular crop, no dark border).
_PROFILE_TEMPLATE = _ASSETS / "profile-new.png"
_PROFILE_FRAME_QUAD = (
    (288, 266),   # top-left
    (898, 179),   # top-right
    (1046, 711),  # bottom-right
    (389, 818),   # bottom-left
)
# Source avatar is resized to this square edge before being warped
# onto the quad. Large enough that the warped result has no blur at
# the actual quad scale (~700px on the long side).
_PROFILE_AVATAR_SRC_SIZE = 1024

# Two-card row at the bottom, matching the reference (Image 9 / 10):
#   * left wide card → ``@username``
#   * right narrow card → "Депозит" small label + ``$ N`` value
# Both cards share the same height and corner radius so they visually
# rhyme; the radius matches the frame's own rounded corners.
_PROFILE_CARD_CORNER_RADIUS = 36
_PROFILE_CARD_Y = 1175
_PROFILE_CARD_H = 150

_PROFILE_USERNAME_CARD_CENTER = (415, _PROFILE_CARD_Y)
_PROFILE_USERNAME_CARD_W = 770
_PROFILE_USERNAME_SIZE = 60
_PROFILE_USERNAME_MAX_WIDTH = 700

_PROFILE_DEPOSIT_CARD_CENTER = (1027, _PROFILE_CARD_Y)
_PROFILE_DEPOSIT_CARD_W = 395
_PROFILE_DEPOSIT_LABEL_XY = (1027, _PROFILE_CARD_Y - 32)
_PROFILE_DEPOSIT_LABEL_SIZE = 28
_PROFILE_DEPOSIT_VALUE_XY = (1027, _PROFILE_CARD_Y + 18)
_PROFILE_DEPOSIT_VALUE_SIZE = 64
_PROFILE_DEPOSIT_VALUE_MAX_WIDTH = 340


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


def _draw_text_centered(
    img: Image.Image,
    *,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    """Draw ``text`` centred horizontally and vertically on ``xy``."""
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    cx, cy = xy
    draw.text((cx - w // 2 - bbox[0], cy - h // 2 - bbox[1]), text, fill=fill, font=font)


def _paste_centered(base: Image.Image, overlay: Image.Image, center: tuple[int, int]) -> None:
    """Paste ``overlay`` (RGBA) onto ``base`` centred on ``center``."""
    ow, oh = overlay.size
    cx, cy = center
    base.paste(overlay, (cx - ow // 2, cy - oh // 2), overlay)


def _perspective_coeffs(
    src: tuple[tuple[float, float], ...],
    dst: tuple[tuple[float, float], ...],
) -> list[float]:
    """Compute the 8 coefficients for ``Image.transform(PERSPECTIVE)``.

    Given four ``src`` points (where each ``dst`` corner should sample
    from in the *output* image) returns the homography that
    :meth:`PIL.Image.transform` consumes for ``PERSPECTIVE``. Solves
    the 8×8 system via plain Gaussian elimination — no numpy needed.
    """
    # Build the 8×9 augmented matrix Ax = b.
    matrix = []
    for (sx, sy), (dx, dy) in zip(src, dst, strict=True):
        matrix.append([dx, dy, 1, 0, 0, 0, -sx * dx, -sx * dy, sx])
        matrix.append([0, 0, 0, dx, dy, 1, -sy * dx, -sy * dy, sy])
    # Forward elimination
    n = 8
    for i in range(n):
        # find pivot
        pivot = max(range(i, n), key=lambda r: abs(matrix[r][i]))
        matrix[i], matrix[pivot] = matrix[pivot], matrix[i]
        piv = matrix[i][i]
        if piv == 0:
            raise ValueError("singular perspective system")
        for j in range(i + 1, n):
            factor = matrix[j][i] / piv
            for k in range(i, n + 1):
                matrix[j][k] -= factor * matrix[i][k]
    # Back-substitute
    coeffs = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = matrix[i][n] - sum(matrix[i][j] * coeffs[j] for j in range(i + 1, n))
        coeffs[i] = s / matrix[i][i]
    return coeffs


def _warp_avatar_to_quad(
    avatar: Image.Image, quad: tuple[tuple[int, int], ...], canvas_size: tuple[int, int]
) -> Image.Image:
    """Perspective-warp a square ``avatar`` onto ``quad`` (TL,TR,BR,BL).

    Returns an RGBA image the size of the eventual paste canvas with
    the avatar drawn inside the quad and everything outside fully
    transparent.
    """
    src_w, src_h = avatar.size
    # Quad in OUTPUT coords → tell PIL which SRC pixel each OUTPUT
    # corner samples from. The output canvas is ``canvas_size``; the
    # avatar is full-size, so the four src corners are simply the
    # avatar's own corners.
    src_corners = (
        (0, 0),
        (src_w - 1, 0),
        (src_w - 1, src_h - 1),
        (0, src_h - 1),
    )
    coeffs = _perspective_coeffs(src_corners, quad)
    warped = avatar.transform(
        canvas_size,
        Image.PERSPECTIVE,
        coeffs,
        resample=Image.BICUBIC,
    )
    # Build an alpha mask that's opaque only inside the quad polygon.
    mask = Image.new("L", canvas_size, 0)
    ImageDraw.Draw(mask).polygon(list(quad), fill=255)
    if warped.mode != "RGBA":
        warped = warped.convert("RGBA")
    warped.putalpha(mask)
    return warped


def _avatar_for_frame(avatar_png: bytes, canvas_size: tuple[int, int]) -> Image.Image:
    """Decode ``avatar_png`` and warp it onto ``_PROFILE_FRAME_QUAD``."""
    src = Image.open(io.BytesIO(avatar_png)).convert("RGBA")
    src = ImageOps.fit(src, (_PROFILE_AVATAR_SRC_SIZE, _PROFILE_AVATAR_SRC_SIZE), Image.LANCZOS)
    return _warp_avatar_to_quad(src, _PROFILE_FRAME_QUAD, canvas_size)


def _apply_dot_overlay(
    base: Image.Image, asset: str, center: tuple[int, int], card_w: int
) -> None:
    """Resize ``asset`` to ``card_w × _PROFILE_CARD_H``, boost its
    alpha so the dotted pattern is visible on dark backgrounds, then
    clip to the rounded-rect card shape and composite onto ``base``."""
    try:
        overlay = _boost_alpha(Image.open(_ASSETS / asset).convert("RGBA"))
    except FileNotFoundError:
        return
    overlay = overlay.resize((card_w, _PROFILE_CARD_H), Image.LANCZOS)
    mask = Image.new("L", overlay.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, overlay.size[0], overlay.size[1]),
        radius=_PROFILE_CARD_CORNER_RADIUS,
        fill=255,
    )
    from PIL import ImageChops

    r, g, b, a = overlay.split()
    a = ImageChops.multiply(a, mask)
    clipped = Image.merge("RGBA", (r, g, b, a))
    _paste_centered(base, clipped, center)


def _boost_alpha(im: Image.Image, factor: float = 8.0) -> Image.Image:
    """Multiply the alpha channel by ``factor`` (clamped to 255).

    The source ``user-info-bg.png`` / ``user-stat-bg.png`` overlays
    have very low max-alpha (~22), which makes them invisible on a
    dark template. Boosting brings out their shape without changing
    the colour palette.
    """
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    r, g, b, a = im.split()
    lut = [min(255, int(v * factor)) for v in range(256)]
    a = a.point(lut)
    return Image.merge("RGBA", (r, g, b, a))


def _paste_label_card(
    base: Image.Image,
    center: tuple[int, int],
    *,
    width: int,
    height: int,
    radius: int = _PROFILE_CARD_CORNER_RADIUS,
) -> None:
    """Paste a soft rounded-rect dark card centred on ``center`` so a
    label drawn over it reads against the bright/cluttered background
    of the profile template."""
    card = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle(
        (0, 0, width, height),
        radius=radius,
        fill=(15, 15, 17, 165),
        outline=(245, 204, 29, 90),
        width=2,
    )
    _paste_centered(base, card, center)


def _placeholder_avatar_square(size: int, initial: str) -> Image.Image:
    """Fallback square avatar with a single capitalised initial."""
    img = Image.new("RGBA", (size, size), (36, 36, 38, 255))
    draw = ImageDraw.Draw(img)
    letter = (initial or "?").strip()[:1].upper() or "?"
    font = _font(int(size * 0.55))
    bbox = draw.textbbox((0, 0), letter, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(
        (size // 2 - tw // 2 - bbox[0], size // 2 - th // 2 - bbox[1]),
        letter,
        fill=_WHITE,
        font=font,
    )
    return img


def render_deals(*, total_volume: float, deal_count: int, sale_count: int) -> bytes:
    # A9-L-2 — see prior comment; the parameter name predates the
    # template rework and the caller already passes ``completed_count``
    # because there's no longer a single-currency volume to sum.
    img = Image.open(_ASSETS / "deals.jpg").convert("RGB")
    draw = ImageDraw.Draw(img)
    # Paint over the template's pre-baked decorative ``$`` so it
    # doesn't double up under our value.
    draw.rectangle(_DEALS_TEMPLATE_DOLLAR_BBOX, fill=_DEALS_CARD_BG)
    sum_text = f"$ {_fmt_money(total_volume)}"
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


def render_profile(
    *,
    username: str | None,
    deposit: float,
    avatar_png: bytes | None = None,
) -> bytes:
    """Compose the profile banner with the user's avatar overlaid on
    the wooden-frame template.

    ``avatar_png`` is raw PNG/JPEG bytes (downloaded via aiogram's
    ``Bot.get_user_profile_photos`` + ``Bot.download``); pass ``None``
    to render a placeholder with the first letter of the username.
    """
    base = Image.open(_PROFILE_TEMPLATE).convert("RGBA")
    canvas_size = base.size

    # 1) Avatar warped to fill the wooden frame's central panel (a
    # rotated quadrilateral, NOT a circle). Falls back to a square
    # placeholder + initial when no avatar or decode fails.
    avatar_src: Image.Image | None = None
    if avatar_png:
        try:
            avatar_src = Image.open(io.BytesIO(avatar_png)).convert("RGBA")
            avatar_src = ImageOps.fit(
                avatar_src,
                (_PROFILE_AVATAR_SRC_SIZE, _PROFILE_AVATAR_SRC_SIZE),
                Image.LANCZOS,
            )
        except Exception as exc:  # noqa: BLE001 — bad upstream image
            logger.warning("avatar decode failed, using placeholder: %s", exc)
            avatar_src = None
    if avatar_src is None:
        avatar_src = _placeholder_avatar_square(
            _PROFILE_AVATAR_SRC_SIZE, (username or "?")[:1]
        )
    warped = _warp_avatar_to_quad(avatar_src, _PROFILE_FRAME_QUAD, canvas_size)
    base.alpha_composite(warped)

    # 2) two-card layout under the frame:
    #    * left wide  card → ``@username``
    #    * right narrow card → "Депозит" label + ``$ N`` value
    # Each card is a rounded-rect halo with a soft yellow stroke, on
    # top of which we paste the (boosted-alpha) decorative dotted
    # PNG so the artwork direction matches reference Image 9.
    _paste_label_card(
        base,
        _PROFILE_USERNAME_CARD_CENTER,
        width=_PROFILE_USERNAME_CARD_W,
        height=_PROFILE_CARD_H,
    )
    _paste_label_card(
        base,
        _PROFILE_DEPOSIT_CARD_CENTER,
        width=_PROFILE_DEPOSIT_CARD_W,
        height=_PROFILE_CARD_H,
    )

    # Decorative dotted-grid overlays: resized to the card size and
    # clipped to the same rounded-rect mask so the pattern never
    # spills past the card's curved corners.
    _apply_dot_overlay(
        base, "user-info-bg.png", _PROFILE_USERNAME_CARD_CENTER, _PROFILE_USERNAME_CARD_W
    )
    _apply_dot_overlay(
        base, "user-stat-bg.png", _PROFILE_DEPOSIT_CARD_CENTER, _PROFILE_DEPOSIT_CARD_W
    )

    # 3) username text — centred in the wide left card.
    label = f"@{username}" if username else "—"
    tmp_draw = ImageDraw.Draw(base)
    username_font = _autofit(
        tmp_draw, label, _PROFILE_USERNAME_SIZE, _PROFILE_USERNAME_MAX_WIDTH
    )
    _draw_text_centered(
        base,
        xy=_PROFILE_USERNAME_CARD_CENTER,
        text=label,
        font=username_font,
        fill=_WHITE,
    )

    # 4) "Депозит" label (small, white) + ``$ N`` value (large, yellow)
    # in the narrow right card.
    _draw_text_centered(
        base,
        xy=_PROFILE_DEPOSIT_LABEL_XY,
        text="Депозит",
        font=_font(_PROFILE_DEPOSIT_LABEL_SIZE),
        fill="#C8C8C8",
    )
    deposit_text = f"$ {_fmt_money(deposit)}"
    deposit_font = _autofit(
        tmp_draw,
        deposit_text,
        _PROFILE_DEPOSIT_VALUE_SIZE,
        _PROFILE_DEPOSIT_VALUE_MAX_WIDTH,
    )
    _draw_text_centered(
        base,
        xy=_PROFILE_DEPOSIT_VALUE_XY,
        text=deposit_text,
        font=deposit_font,
        fill=_YELLOW,
    )

    out = io.BytesIO()
    base.convert("RGB").save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()
