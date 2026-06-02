from __future__ import annotations

import json
import math
import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, PlainSerializer, field_validator, model_validator


def _validate_https_or_media_url(v: str, *, what: str, max_len: int = 1024) -> str:
    """Audit L-3 — strict URL validator for user-supplied avatar/banner/forum links.

    Pre-fix the validators only checked a lowercase ``startswith``
    prefix, which let edge-case schemes through. For example:

    * ``https:javascript:alert(1)`` — ``startswith("https://")`` is
      ``False`` so we already rejected this, but a sloppy variant
      ``https:/javascript`` slipped through if the prefix was the
      single-slash form. Parsing with ``urlparse`` makes the host
      requirement explicit.
    * URLs with embedded whitespace / control characters (``\\n``,
      ``\\r``, ``\\t``) — ``urlparse`` retains them but the host
      check below rejects anything that doesn't look like a domain.
    * Empty hosts (``https:///path``) — these pass a naive prefix
      check; parsing surfaces them as ``netloc == ''`` so we can
      reject explicitly.

    The validator allows two shapes:

    1. ``https://<host>[...]`` — ``host`` is any non-empty token
       matching the conservative ``[a-z0-9][a-z0-9.-]*`` shape.
       ``http://`` is intentionally disallowed (downgrade vector
       inside a TMA shell that only serves https resources).
    2. ``/media/...`` — a relative path served by the backend's own
       static handler. Used by uploaded avatars/banners.

    Any other scheme (``javascript:``, ``data:``, ``file:``,
    ``tg:``, ``mailto:``, ...) raises ``ValueError``. The caller
    plugs the field-specific error message via the ``what`` arg.
    """
    v = v.strip()
    if not v:
        raise ValueError(f"{what} не может быть пустым")
    if len(v) > max_len:
        raise ValueError(f"{what} слишком длинный")
    # Reject embedded control characters / whitespace; urlparse keeps
    # them silently which lets an attacker smuggle CR/LF into a
    # header-injection downstream.
    for ch in v:
        if ord(ch) < 0x20 or ch in (" ", "\x7f"):
            raise ValueError(f"{what} содержит недопустимые символы")
    if v.startswith("/media/"):
        # Backend-served path — fine, no scheme to validate.
        return v
    parsed = urlparse(v)
    if parsed.scheme.lower() != "https":
        raise ValueError(f"{what} должен быть https:// ссылкой")
    host = (parsed.netloc or "").lower()
    if not host:
        raise ValueError(f"{what} должен содержать хост")
    # Reject userinfo (``user@host``) — Telegram's link preview will
    # cheerfully render ``https://example.com@evil.com/`` as
    # ``example.com``, which the user will trust. Strip-and-reject.
    if "@" in host:
        raise ValueError(f"{what} не может содержать userinfo")
    return v


# H-1: internal calculations use ``Decimal`` for precision, but the
# JSON wire format emits a plain number (``float``) so the frontend
# (JavaScript) can consume values without a string→number parse step.
MoneyDecimal = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float)]

# ── Users ──────────────────────────────────────────────


# Audit (continuation) M-1 — backend whitelist for ``Forum.name``.
# Pre-fix only the frontend ``AddForumPage.tsx`` enforced the list
# of approved forum names (its ``FORUM_OPTIONS`` constant); a caller
# hitting ``PATCH /api/me`` directly (curl/postman with a valid
# initData) could record an arbitrary string in ``Forum.name`` and
# have it rendered on their public profile via ``UserPublicOut.forums``.
# That's a moderation hole (spam / illicit links / fake brand names).
#
# Kept in lockstep with ``frontend/src/pages/profile/AddForumPage.tsx``
# ``FORUM_OPTIONS`` until the architectural fix (a ``GET /api/forums``
# endpoint sourcing both sides from the same DB row) lands as a
# follow-up. ``"Другое"`` is a frontend-only catch-all that lets the
# user submit a custom name; the backend still rejects anything not
# in the whitelist below — so that ``"Другое"`` is allowed as a
# *name* (the user picks the option, then types the real forum
# name into the URL field), keeping the existing UX flow intact.
FORUM_WHITELIST: frozenset[str] = frozenset(
    {
        "Darkmoney",
        "Probiv",
        "Verified",
        "DarkNet",
        "Lolzteam",
        "Maza",
        "Korovka",
        "Carder.market",
        "Другое",
    }
)

# Audit v3 A-1 — the catch-all "Other" option that lets a user pick
# ``FORUM_FREEFORM_OPTION`` from the dropdown and then type whatever
# URL they want. Pre-fix the literal lived in
# ``frontend/src/pages/profile/AddForumPage.tsx`` and was duplicated
# inside :data:`FORUM_WHITELIST` here — drift between the two would
# silently desync the dropdown from the write-boundary validator. The
# new ``GET /api/forums`` endpoint returns the canonical list plus
# this marker so the frontend renders whatever the backend says is
# valid, and both sides agree on the spelling.
FORUM_FREEFORM_OPTION: str = "Другое"


class ForumListOut(BaseModel):
    """Public list of approved forum names served by ``GET /api/forums``.

    Audit v3 A-1 — single source of truth for the dropdown rendered
    on ``AddForumPage.tsx``. Pre-fix the frontend hard-coded
    ``FORUM_OPTIONS`` and drift between the two was caught only by
    ``tests/test_forum_whitelist_sync.py``; with this endpoint the
    frontend fetches the canonical list at runtime.

    ``freeform_option`` is the marker name that the UI treats as
    "pick this and type a custom URL"; it is always one of the
    entries in ``forums``.
    """

    forums: list[str]
    freeform_option: str


class ForumOut(BaseModel):
    """Serialised view of a ``Forum`` row.

    Audit (continuation) M-1 — *output* validation is kept lenient so
    legacy rows whose ``name`` predates the whitelist still render in
    public profiles. Whitelist enforcement lives on the matching input
    schema :class:`ForumIn` below, which is what
    ``UserUpdate.forums`` actually accepts on the wire. Keeping the
    write boundary strict + the read boundary tolerant is the same
    pattern :func:`_validate_https_or_media_url` follows for legacy
    avatar URLs.
    """

    name: str
    url: str

    @field_validator("name")
    @classmethod
    def _name_ok(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Имя форума не может быть пустым")
        if len(v) > 64:
            raise ValueError("Имя форума слишком длинное (≤64)")
        return v

    @field_validator("url")
    @classmethod
    def _url_ok(cls, v: str) -> str:
        # Audit L-3 — was a ``startswith("https://")`` check, now a
        # full parse via ``_validate_https_or_media_url``. The
        # ``/media/...`` shape isn't useful for a forum link (those
        # always point at an external community), so callers reject
        # it explicitly after the shared validator runs.
        v = _validate_https_or_media_url(v or "", what="Ссылка", max_len=512)
        if v.startswith("/media/"):
            raise ValueError("Ссылка должна быть внешней (https://)")
        return v


class ForumIn(ForumOut):
    """Input schema for ``UserUpdate.forums``.

    Audit (continuation) M-1 — splits the write boundary off the read
    one (:class:`ForumOut`). The shared parent enforces the
    URL/length/non-empty rules every call site cares about; this
    subclass adds the whitelist gate so a caller hitting
    ``PATCH /api/me`` directly (curl/postman with a valid initData)
    can't record an arbitrary forum name and have it render on their
    public profile. See :data:`FORUM_WHITELIST`.
    """

    @field_validator("name")
    @classmethod
    def _name_in_whitelist(cls, v: str) -> str:
        # Re-runs the parent's non-empty / length-cap check first so
        # the error messages stay in the same Russian-locale shape;
        # then enforces the whitelist as the *additional* boundary.
        v = (v or "").strip()
        if not v:
            raise ValueError("Имя форума не может быть пустым")
        if len(v) > 64:
            raise ValueError("Имя форума слишком длинное (≤64)")
        if v not in FORUM_WHITELIST:
            raise ValueError("Неизвестный форум")
        return v


class UserOut(BaseModel):
    """Authenticated user's own profile (``/api/me``).

    Includes Telegram-side identifier (``user_id`` = ``tg_user_id``) and
    DM preferences. For the public listing / detail endpoints used to
    render *other* users see :class:`UserPublicOut`, which omits these
    fields per audit v9 Comments 29/30.
    """

    id: int
    user_id: int
    username: str | None
    display_name: str
    photo_url: str | None
    banner_url: str | None
    deposit: MoneyDecimal
    description: str
    prefix: str | None
    is_admin: bool
    is_arbiter: bool
    is_vip: bool = False
    is_banned: bool = False
    is_frozen: bool = False
    admin: int
    good: int
    bad: int
    rating: MoneyDecimal
    reviews_count: int
    deals_count: int
    # Item 11 — break ``deals_count`` (= ``deals_total``) into the
    # success / failed / arbitrage tiles already tracked on the
    # ``User`` row. Admin panel already exposes these via
    # :class:`AdminUserDetailOut`; surfacing them here lets the
    # regular profile show the same portfolio breakdown.
    deals_success: int
    deals_failed: int
    deals_arbitrage: int
    deals_sum: MoneyDecimal
    online: bool
    forums: list[ForumOut]
    dm_deals: bool = True
    dm_deposits: bool = True
    dm_system: bool = True
    is_anonymous_deals: bool = False
    is_hidden_profile: bool = False
    country: str | None = None
    # Items 13/15 — fiat currency code the user picked as their
    # "main" balance shown on the new ``ProfilePage`` fiat-balance
    # card. ``None`` ⇒ "not picked"; the UI defaults to USD. Restricted
    # to ``Currency.kind == 'fiat'`` rows via the PATCH ``/api/me``
    # validator; surfaced only on ``UserOut`` (the requester's own
    # profile) — other users have no reason to see it.
    display_currency_code: str | None = None


class UserPublicOut(BaseModel):
    """Public profile shown on ``/api/users`` and ``/api/users/{username}``.

    Comment 29 (audit v9): omit ``user_id`` (= ``tg_user_id``). Telegram
    IDs were leaking through the search/detail endpoints, which let any
    user enumerate the tg_user_id of every visible profile.

    Comment 30 (audit v9): also omit DM-preference flags (``dm_deals`` /
    ``dm_deposits`` / ``dm_system``) and the moderation flags
    (``is_banned`` / ``is_frozen``). Those remain in :class:`UserOut`
    (the requester's own ``/api/me``) and :class:`AdminUserDetailOut`
    (admin panel), but they have no business being on the public card.
    """

    id: int
    username: str | None
    display_name: str
    photo_url: str | None
    banner_url: str | None
    deposit: MoneyDecimal
    description: str
    prefix: str | None
    is_admin: bool
    is_arbiter: bool
    is_vip: bool = False
    admin: int
    good: int
    bad: int
    rating: MoneyDecimal
    reviews_count: int
    deals_count: int
    # Item 11 — public-facing portfolio breakdown (mirrors the
    # admin DTO). See :class:`UserOut` for the same rationale.
    deals_success: int
    deals_failed: int
    deals_arbitrage: int
    deals_sum: MoneyDecimal
    online: bool
    forums: list[ForumOut]
    is_anonymous_deals: bool = False
    is_hidden_profile: bool = False
    country: str | None = None


class UserUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    banner_url: str | None = None
    photo_url: str | None = None
    # Audit (continuation) M-1 — write boundary validates against the
    # backend whitelist via :class:`ForumIn` (subclass of
    # :class:`ForumOut`). The serialised view used by the read-side
    # ``UserOut`` / ``UserPublicOut`` still uses ``ForumOut`` so legacy
    # rows whose ``name`` predates the whitelist keep rendering.
    forums: list[ForumIn] | None = None
    dm_deals: bool | None = None
    dm_deposits: bool | None = None
    dm_system: bool | None = None
    is_anonymous_deals: bool | None = None
    is_hidden_profile: bool | None = None
    # ISO-3166-1 alpha-2 (``"RU"``, ``"US"``, ...). Empty string clears
    # the stored country (``None`` in the DB). Validated against the
    # ``^[A-Z]{2}$`` shape only; the human-readable name + flag emoji
    # live in ``frontend/src/lib/countries.ts`` so the backend never
    # ships an ISO list (no ``pycountry`` dep, no seed data).
    country: str | None = None
    # Items 13/15 — fiat currency code the user picked as the "main"
    # balance shown on the ``ProfilePage`` fiat-balance card. Empty
    # string clears the column (renders as the USD fallback); the
    # validator below uppercases and length-checks the value, and the
    # PATCH ``/api/me`` handler verifies the code points at an active
    # ``Currency`` row with ``kind == 'fiat'``.
    display_currency_code: str | None = None

    @field_validator("photo_url")
    @classmethod
    def _photo_url_ok(cls, v: str | None) -> str | None:
        # Audit L-3 — full URL parse via shared helper. Pre-fix was
        # ``startswith("https://")``, which silently allowed shapes
        # like ``https:///alert.js`` (empty host) and embedded
        # control characters. The shared helper rejects both, in
        # addition to all non-``https``/``/media`` schemes.
        if v is None or v == "":
            return v
        return _validate_https_or_media_url(v, what="Фото", max_len=1024)

    @field_validator("display_name")
    @classmethod
    def _display_name_ok(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if len(v) > 64:
            raise ValueError("Никнейм слишком длинный (≤64)")
        return v

    @field_validator("description")
    @classmethod
    def _description_ok(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if len(v) > 1024:
            raise ValueError("Описание слишком длинное (≤1024)")
        return v

    @field_validator("banner_url")
    @classmethod
    def _banner_url_ok(cls, v: str | None) -> str | None:
        # Audit L-3 — same hardening as ``photo_url`` above.
        if v is None or v == "":
            return v
        return _validate_https_or_media_url(v, what="Баннер", max_len=1024)

    @field_validator("forums")
    @classmethod
    def _forums_ok(cls, v: list[ForumIn] | None) -> list[ForumIn] | None:
        if v is None:
            return v
        if len(v) > 10:
            raise ValueError("Слишком много форумов (≤10)")
        return v

    @field_validator("country")
    @classmethod
    def _country_ok(cls, v: str | None) -> str | None:
        # ``None`` = leave as-is on PATCH (field omitted from body).
        # Empty string = explicit clear (DB stores ``NULL``); we
        # normalise to ``None`` here so the router's
        # ``user.country = body.country`` branch works uniformly.
        # Otherwise: must be exactly two ASCII letters; we upper-case
        # so ``"ru"`` and ``"RU"`` both round-trip to ``"RU"`` in the
        # DB. No external ISO-list dependency — the canonical list of
        # codes lives client-side in ``frontend/src/lib/countries.ts``.
        if v is None or v == "":
            return None
        v = v.strip()
        if len(v) != 2 or not v.isalpha() or not v.isascii():
            raise ValueError("Код страны должен быть ISO-3166-1 alpha-2 (2 буквы)")
        return v.upper()

    @field_validator("display_currency_code")
    @classmethod
    def _display_currency_code_ok(cls, v: str | None) -> str | None:
        # Shape-only validation here (the closed set of *active*
        # currency codes is enforced by the PATCH ``/api/me`` handler
        # against the live ``currencies`` table — keeping that check
        # off the pydantic layer means schema validation stays a pure
        # function, no DB round-trip). Empty string normalises to
        # ``None`` (clears the column → UI falls back to USD).
        if v is None or v == "":
            return None
        v = v.strip()
        if not v:
            return None
        if len(v) > 8 or not v.isalnum() or not v.isascii():
            raise ValueError("Код валюты должен быть до 8 ASCII-символов")
        return v.upper()


# ── Categories ─────────────────────────────────────────


class CategoryOut(BaseModel):
    id: int
    slug: str
    name: str
    icon_key: str
    services_count: int


# ── Services ───────────────────────────────────────────


MAX_SERVICE_PHOTOS = 6

# Maximum length for user-supplied free-form description fields
# (services, deals). Matches the existing cap on the admin-side
# ``AdminServiceUpdateIn._description_ok`` so user-initiated and
# admin-initiated writes converge on the same invariant; without
# this limit the public create / update endpoints accepted arbitrary-
# length payloads that ended up in the search-vector pipeline and
# admin-panel text views, with predictable bloat consequences.
MAX_DESCRIPTION_LEN = 4000


def _validate_description(v: str | None) -> str | None:
    """Cap free-form description length.

    ``None`` means "don't touch" (only meaningful on update schemas);
    the empty-string default on create schemas is permitted as-is so
    optional description fields stay optional.
    """
    if v is None:
        return v
    if len(v) > MAX_DESCRIPTION_LEN:
        raise ValueError(f"Описание слишком длинное (≤{MAX_DESCRIPTION_LEN})")
    return v


def _reject_non_finite_money(v: Decimal | float | int | None) -> Decimal | None:
    """Coerce to ``Decimal`` and reject non-finite sentinels on money fields.

    H-1: all public-API money fields are ``Decimal`` now.  Pydantic v2
    coerces JSON numbers to ``Decimal`` natively, but ``float`` inputs
    via Python callers or ``"Infinity"``/``"NaN"`` strings still need
    guarding.
    """
    if v is None:
        return None
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError("Сумма должна быть конечным числом")
        v = Decimal(str(v))
    elif isinstance(v, int):
        v = Decimal(v)
    if not v.is_finite():
        raise ValueError("Сумма должна быть конечным числом")
    return v


def _validate_optional_positive_int_id(v: object, *, what: str = "ID") -> object:
    if v is None:
        return v
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError(f"{what} должен быть целым числом")
    if v <= 0:
        raise ValueError(f"{what} должен быть положительным числом")
    return v


def _validate_optional_non_negative_int(v: object, *, what: str = "Значение") -> int | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError(f"{what} должно быть целым числом")
    if v < 0:
        raise ValueError(f"{what} не может быть отрицательным")
    return v


def _validate_service_photos(v: list[str] | None) -> list[str] | None:
    # V12-UI — gatekeep the photo list (length + each entry's scheme)
    # in one place so both ``ServiceCreate`` and ``ServiceUpdate``
    # behave identically. ``None`` means "don't touch" (only on
    # update); the create path explicitly defaults to ``[]``.
    if v is None:
        return v
    if len(v) > MAX_SERVICE_PHOTOS:
        raise ValueError(f"Слишком много фотографий (≤{MAX_SERVICE_PHOTOS})")
    # Audit 3.8 — drop duplicates while preserving the caller's order.
    # The DB column is ``photo_urls JSONB`` with a length cap (≤6) but
    # no uniqueness constraint, so without this filter a client could
    # render the same image six times in the gallery (typically a UI
    # bug, occasionally a quota-evasion attempt).
    cleaned: list[str] = []
    seen: set[str] = set()
    for entry in v:
        s = (entry or "").strip()
        if not s:
            continue
        if len(s) > 1024:
            raise ValueError("Слишком длинная ссылка на фото")
        low = s.lower()
        if not (low.startswith("https://") or low.startswith("/media/")):
            raise ValueError("Фото должно быть https:// или /media/... ссылкой")
        if s in seen:
            continue
        seen.add(s)
        cleaned.append(s)
    return cleaned


class ServiceOut(BaseModel):
    id: int
    owner_username: str | None
    title: str
    description: str
    price: MoneyDecimal
    currency: str
    status: str
    category: CategoryOut
    created_at: datetime | None
    photo_urls: list[str] = Field(default_factory=list)


class ServiceCreate(BaseModel):
    category_slug: str
    title: str
    description: str = ""
    # L-2: ``ge=0`` mirrors the explicit ``price < 0`` guard in the
    # router. The non-finite check below catches ``NaN``/``±inf`` JSON
    # values that bypass the ``ge=0`` comparison (``NaN < 0`` is
    # ``False``).
    price: Decimal = Field(default=Decimal(0), ge=0)
    photo_urls: list[str] = Field(default_factory=list)

    @field_validator("price")
    @classmethod
    def _price_finite(cls, v: Decimal | float) -> Decimal:
        result = _reject_non_finite_money(v)
        return result if result is not None else Decimal(0)

    @field_validator("description")
    @classmethod
    def _description_ok(cls, v: str) -> str:
        return _validate_description(v) or ""

    @field_validator("photo_urls")
    @classmethod
    def _photo_urls_ok(cls, v: list[str]) -> list[str]:
        return _validate_service_photos(v) or []


class ServiceUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    # L-2: same finiteness/non-negative guard as ``ServiceCreate.price``.
    price: Decimal | None = Field(default=None, ge=0)
    status: str | None = None  # draft / active / paused (banned only via admin)
    photo_urls: list[str] | None = None

    @field_validator("price")
    @classmethod
    def _price_finite(cls, v: Decimal | float | None) -> Decimal | None:
        return _reject_non_finite_money(v)

    @field_validator("description")
    @classmethod
    def _description_ok(cls, v: str | None) -> str | None:
        return _validate_description(v)

    @field_validator("photo_urls")
    @classmethod
    def _photo_urls_ok(cls, v: list[str] | None) -> list[str] | None:
        return _validate_service_photos(v)


class ServiceModerationDecision(BaseModel):
    action: str  # "ban" | "unban"
    reason: str = ""


class ServiceOwnerOut(BaseModel):
    """Owner card embedded in :class:`ServiceDetailOut`."""

    id: int
    username: str | None
    display_name: str
    photo_url: str | None
    rating: MoneyDecimal
    deals_count: int
    good: int
    bad: int
    is_admin: bool
    is_arbiter: bool


class ServiceDetailOut(ServiceOut):
    owner: ServiceOwnerOut | None
    comments_count: int
    rating_avg: MoneyDecimal | None
    rating_count: int


class ServiceCommentCreate(BaseModel):
    text: str = ""
    rating: int | None = None

    @field_validator("text")
    @classmethod
    def _text_len(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 1024:
            raise ValueError("Комментарий слишком длинный (≤1024)")
        return v

    @field_validator("rating", mode="before")
    @classmethod
    def _rating_strict_int(cls, v: object) -> object:
        if v is None:
            return v
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("Оценка должна быть целым числом")
        return v

    @field_validator("rating")
    @classmethod
    def _rating_range(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 1 or v > 5:
            raise ValueError("Оценка должна быть от 1 до 5")
        return v


class ServiceCommentOut(BaseModel):
    id: int
    service_id: int
    author_id: int
    author_username: str | None
    author_display_name: str
    author_photo_url: str | None
    text: str
    rating: int | None
    created_at: datetime


# ── Deals ──────────────────────────────────────────────


class DealCreate(BaseModel):
    counterparty: str
    # Audit C1 — ``Literal["buyer"]`` so the caller of ``POST /api/deals``
    # is always the buyer (the side whose balance gets debited into the
    # escrow lock). Pre-fix ``role="seller"`` let any user freeze an
    # arbitrary counterparty's balance for days: ``decline_deal`` /
    # ``accept_deal`` are seller-only and the buyer had no reject path,
    # so the victim's only recourse was waiting out
    # ``inactivity_pending_confirmation_days``. Forcing the role at the
    # schema layer means we reject ``role="seller"`` (and any typo) with
    # a 422 before touching the DB.  Default is provided so legacy
    # clients that omit the field continue to work.
    role: Literal["buyer"] = "buyer"
    # L-1 / M-5: ``ge=Decimal("0.00000001")`` matches the smallest
    # representable amount our 8-fractional-digit ``Numeric(28, 8)``
    # money columns support — i.e. one satoshi for BTC-scale assets.
    amount: Decimal = Field(ge=Decimal("0.00000001"))
    description: str = ""
    currency_code: str = "USDT"
    # Buyer's preferred upstream invoice provider; persisted on the
    # :class:`backend.app.models.Deal` row for the invoice-driven
    # escrow flow. ``"cryptobot"`` keeps legacy clients (no
    # ``payment_provider`` on the wire) backwards-compatible.
    payment_provider: Literal["cryptobot", "crystalpay"] = "cryptobot"

    @field_validator("amount")
    @classmethod
    def _amount_finite(cls, v: Decimal | float) -> Decimal:
        result = _reject_non_finite_money(v)
        return result if result is not None else Decimal(0)

    @field_validator("description")
    @classmethod
    def _description_ok(cls, v: str) -> str:
        return _validate_description(v) or ""


class DealCreateWithTopup(DealCreate):
    """P10 — input for ``POST /api/deals/with-topup``.

    Exactly the same shape as :class:`DealCreate` but routed through
    the commission-via-invoice service entry point. Kept as a separate
    class so the OpenAPI surface stays explicit; the legacy
    ``POST /api/deals`` route now delegates to the same service.
    """


class DealTopupInvoiceOut(BaseModel):
    """P10 — deposit-invoice descriptor returned from the with-topup endpoint.

    Mirrors the shape the frontend already consumes for wallet
    top-ups (``WalletDepositOut``) but renames the fields to match
    the spec's vocabulary (``topup_principal`` + ``commission`` +
    ``total``).
    """

    deposit_id: int
    pay_url: str
    total: MoneyDecimal
    topup_principal: MoneyDecimal
    commission: MoneyDecimal
    paid_total: MoneyDecimal = Decimal("0")
    currency_code: str
    provider: str
    expires_at: datetime | None = None


class DealCreateWithTopupOut(BaseModel):
    """P10 — response from ``POST /api/deals/with-topup``.

    Bundles the new :class:`DealOut` row (status ``pending_topup``)
    with the :class:`DealTopupInvoiceOut` describing the invoice the
    buyer must pay before the deal can be activated.

    P11-D1 — ``invoice`` is ``None`` when the buyer's balance fully
    covers ``amount + commission``; the service short-circuits the
    invoice path and debits the balance directly so the deal lands
    in :data:`DealStatus.pending_confirmation` straight away. The
    frontend uses ``invoice is None`` to skip the pay-the-invoice
    UI and jump to the deal-detail page.
    """

    deal: DealOut
    invoice: DealTopupInvoiceOut | None


class DealCancelRequest(BaseModel):
    reason: str = ""

    @field_validator("reason")
    @classmethod
    def _reason_ok(cls, v: str) -> str:
        # Match the existing ``description`` cap so free-form deal
        # text on the wire is bounded everywhere. Without this, the
        # ``Text``-typed columns ``cancellation_reason`` / ``arbitration_reason``
        # / ``arbitration_note`` would happily accept multi-MB strings.
        return _validate_description(v) or ""


class DealArbitrationRequest(BaseModel):
    reason: str = ""

    @field_validator("reason")
    @classmethod
    def _reason_ok(cls, v: str) -> str:
        return _validate_description(v) or ""


class DealResolveRequest(BaseModel):
    winner: str  # "buyer" or "seller"
    note: str = ""

    @field_validator("winner")
    @classmethod
    def winner_valid(cls, v: str) -> str:
        if v not in ("buyer", "seller"):
            raise ValueError("winner должен быть 'buyer' или 'seller'")
        return v

    @field_validator("note")
    @classmethod
    def _note_ok(cls, v: str) -> str:
        return _validate_description(v) or ""


class DealOut(BaseModel):
    id: int
    buyer: str | None
    seller: str | None
    # Item 21 — counterparty avatar URL on the deal card / detail page.
    # Optional so existing clients ignoring the field keep working.
    buyer_photo_url: str | None = None
    seller_photo_url: str | None = None
    description: str
    status: str
    confirm_buyer: bool
    confirm_seller: bool
    role: str
    created_at: datetime | None
    # PR-3 — multi-currency + state-machine extras.
    currency_code: str | None = None
    amount: MoneyDecimal
    commission_amount: MoneyDecimal | None = None
    in_progress_at: datetime | None = None
    completed_at: datetime | None = None
    cancellation_initiator: str | None = None
    cancellation_reason: str | None = None
    cancellation_requested_at: datetime | None = None
    arbitration_initiator: str | None = None
    arbitration_reason: str | None = None
    arbitration_resolved_by: str | None = None
    arbitration_resolution: str | None = None
    arbitration_resolved_at: datetime | None = None
    # Persisted upstream invoice provider chosen by the buyer at
    # deal-create time. Surfaced on the wire so the deal detail page
    # can render the right provider badge without an extra lookup.
    payment_provider: str = "cryptobot"
    # P10 — commission-via-invoice flow.
    topup_deposit_id: int | None = None
    commission_paid: bool = False
    # P10 — inline copy of the deposit invoice so the frontend can
    # resume the pay flow after a reload of an existing
    # ``pending_topup`` deal without a separate ``GET`` round-trip.
    # Populated by ``routers/deals._deal_out`` only when the deal is
    # still in ``pending_topup`` AND the linked deposit row is
    # ``pending``; otherwise it stays ``None`` (deal has already been
    # paid, expired, or never had a topup invoice in the first place
    # — i.e. the legacy ``POST /api/deals`` balance-only path).
    topup_invoice: DealTopupInvoiceOut | None = None


# ── Reviews ────────────────────────────────────────────


class MediaOut(BaseModel):
    id: int
    kind: str
    url: str
    name: str
    size: int
    content_type: str
    created_at: datetime | None


# ── Deal chat ──────────────────────────────────────────


class DealMessageCreate(BaseModel):
    text: str = ""
    attachments: list[int] = []

    @field_validator("text")
    @classmethod
    def _text_len(cls, v: str) -> str:
        if len(v) > 4000:
            raise ValueError("Сообщение слишком длинное (≤4000)")
        return v

    @field_validator("attachments")
    @classmethod
    def _attachments_len(cls, v: list[int]) -> list[int]:
        if len(v) > 10:
            raise ValueError("Не больше 10 вложений за сообщение")
        if any(mid <= 0 for mid in v):
            raise ValueError("ID вложений должны быть положительными числами")
        return v

    @field_validator("attachments", mode="before")
    @classmethod
    def _attachments_strict_ints(cls, v: object) -> object:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("attachments должен быть списком ID")
        for item in v:
            # JSON bools and strings used to be coerced by Pydantic
            # (``true`` -> media id 1, ``"1"`` -> media id 1). Keep
            # attachment references as explicit integer primary keys.
            if isinstance(item, bool) or not isinstance(item, int):
                raise ValueError("ID вложений должны быть целыми числами")
        return v


class DealMessageOut(BaseModel):
    id: int
    deal_id: int
    sender_id: int
    sender_username: str | None
    text: str
    attachments: list[MediaOut]
    created_at: datetime


class ReviewCreate(BaseModel):
    target_username: str
    rating: int
    text: str = ""
    deal_id: int

    @field_validator("deal_id", mode="before")
    @classmethod
    def _deal_id_strict_positive(cls, v: object) -> object:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("ID сделки должен быть целым числом")
        if v <= 0:
            raise ValueError("ID сделки должен быть положительным числом")
        return v

    @field_validator("rating", mode="before")
    @classmethod
    def _rating_strict_int(cls, v: object) -> object:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("Рейтинг должен быть целым числом")
        return v

    @field_validator("rating")
    @classmethod
    def _rating_range(cls, v: int) -> int:
        if v < 1 or v > 5:
            raise ValueError("Рейтинг должен быть от 1 до 5")
        return v

    @field_validator("text")
    @classmethod
    def _text_len(cls, v: str) -> str:
        if len(v) > 1024:
            raise ValueError("Текст отзыва слишком длинный (≤1024)")
        return v


class ReviewOut(BaseModel):
    id: int
    deal_id: int | None
    author_username: str | None
    target_username: str | None
    rating: int
    text: str
    created_at: datetime


# ── Notifications ──────────────────────────────────────


class NotificationOut(BaseModel):
    id: int
    type: str
    title: str
    body: str
    payload: dict | None

    @field_validator("payload", mode="before")
    @classmethod
    def parse_payload(cls, v: str | dict | None) -> dict | None:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v

    is_read: bool
    created_at: datetime


class NotificationCountersOut(BaseModel):
    all: int
    deals: int
    deposits: int
    system: int
    unread: int


# ── Payments ───────────────────────────────────────────


# H-1 — ``InvoiceCreateReq`` / ``InvoiceOut`` / ``InvoiceStatusOut`` /
# ``DepositReq`` retired alongside the legacy ``User.balance`` ledger.
# Multi-currency wallet deposits use ``WalletDepositCreateReq`` /
# ``WalletDepositOut`` defined below.


# ── Wallet (multi-currency) ────────────────────────────


class CurrencyOut(BaseModel):
    id: int
    code: str
    name: str
    network: str
    icon_url: str
    decimals: int
    min_deposit: MoneyDecimal
    min_withdraw: MoneyDecimal
    # ``"crypto"`` (default) or ``"fiat"``. The deposit page uses
    # this to filter the dropdown so the user only sees fiat
    # options; the wallet page can independently decide which
    # balances to render.
    kind: str = "crypto"


class WalletBalanceOut(BaseModel):
    currency: CurrencyOut
    amount: MoneyDecimal
    locked: MoneyDecimal
    total: MoneyDecimal
    updated_at: datetime | None
    # Audit M-7 — string mirrors of the three balance fields. The
    # ``MoneyDecimal`` wire serialiser above casts each ``Decimal``
    # to ``float`` for JSON compatibility; JavaScript then re-reads
    # it as an IEEE-754 double, which silently loses precision at the
    # 10^10-ish scale USDT can hit (a balance of ``99999999.12345678``
    # round-trips as ``99999999.12345679``). The frontend's "Все"
    # button used ``String(current.amount)`` to pre-fill the withdraw
    # input, so the loss-of-precision then leaked into the
    # ``WalletWithdrawCreateReq.amount`` body and the user saw a
    # rounding error appear out of thin air. We now ship a parallel
    # ``*_str`` field for every money column so the frontend can pass
    # the user-visible string straight through to the API (which
    # accepts ``Decimal`` from a string body without going through
    # ``float``). The float field is kept for backward compatibility
    # with older clients that ignore the new ``*_str`` fields.
    amount_str: str
    locked_str: str
    total_str: str


class WalletDepositCreateReq(BaseModel):
    currency_code: str
    amount: Decimal
    # Routing tag for ``services_wallet.create_deposit_invoice``.
    # ``"wallet"`` (default) credits the per-currency ``UserBalance``
    # ledger that funds deals + withdrawals. ``"trust"`` credits the
    # ``User.trust_deposit_balance`` instead — that balance has no
    # spend / withdraw path on purpose (lock-in by design) and only
    # surfaces publicly as ``deposit`` on the user card.
    purpose: Literal["wallet", "trust"] = "wallet"
    # Selects which upstream payment provider the deposit invoice is
    # issued on. ``"cryptobot"`` (default, backwards-compatible) uses
    # Crypto Pay; ``"crystalpay"`` issues a Crystalpay v3 invoice.
    # Both providers feed the same ``WalletDeposit`` row + the same
    # post-payment ``credit_deposit`` path — the routing only affects
    # which API the invoice is created on and which webhook URL the
    # user pays through.
    provider: Literal["cryptobot", "crystalpay"] = "cryptobot"

    @field_validator("amount")
    @classmethod
    def positive(cls, v: Decimal | float) -> Decimal:
        result = _reject_non_finite_money(v)
        if result is None or result <= 0:
            raise ValueError("Сумма должна быть больше нуля")
        return result


class WalletDepositOut(BaseModel):
    id: int
    currency: CurrencyOut
    amount: MoneyDecimal
    status: str
    pay_url: str
    invoice_id: str
    # Mirrors the new ``WalletDeposit.purpose`` column so the frontend
    # can render a different deposit-card title for trust deposits
    # (and so the wallet ``/deposits`` listing can distinguish the two
    # purposes without an extra round-trip).
    purpose: str
    # Mirrors ``WalletDeposit.provider`` so the frontend can render a
    # provider badge on the deposit card / list. The value matches the
    # backend enum on the wire: ``"cryptobot"`` or ``"crystalpay"``.
    provider: str
    created_at: datetime
    paid_at: datetime | None


class WalletWithdrawCreateReq(BaseModel):
    currency_code: str
    amount: Decimal
    # Optional for the current CryptoBot Transfer payout model: the
    # recipient is the user's Telegram identity, not an on-chain address.
    # Legacy clients may still send an address; the service sanitises it
    # and applies the currency regex when one is configured.
    address: str | None = None

    @field_validator("amount")
    @classmethod
    def positive(cls, v: Decimal | float) -> Decimal:
        result = _reject_non_finite_money(v)
        if result is None or result <= 0:
            raise ValueError("Сумма должна быть больше нуля")
        return result

    @field_validator("address")
    @classmethod
    def strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        return v


class WalletWithdrawalOut(BaseModel):
    id: int
    currency: CurrencyOut
    amount: MoneyDecimal
    # ``None`` when the withdrawal was created in CryptoBot Transfer
    # auto-mode (the recipient is identified by ``users.tg_user_id``
    # rather than an on-chain address).
    address: str | None
    status: str
    admin_note: str
    created_at: datetime
    processed_at: datetime | None


# ``WalletAdminWithdrawDecision`` was removed alongside the legacy
# ``/api/wallet/admin/withdrawals`` endpoints. Use
# ``AdminWithdrawalDecideIn`` from the admin module instead.


# ── Support ────────────────────────────────────────────


class SupportPersonOut(BaseModel):
    id: int
    user_id: int
    username: str | None
    display_name: str
    photo_url: str | None
    admin: int
    prefix: str


# ── Admin Panel ────────────────────────────────────────


class AdminDashboardOut(BaseModel):
    """Summary counters for ``/admin/dashboard``."""

    total_users: int
    new_users_24h: int
    new_users_7d: int
    online_users_5min: int
    total_deals: int
    open_deals: int
    open_arbitration: int
    total_services: int
    active_services: int
    banned_users: int
    frozen_users: int
    admins: int
    arbiters: int
    vips: int


class AdminUserListItem(BaseModel):
    """Single row in the ``/admin/users`` listing."""

    id: int
    tg_user_id: int
    username: str | None
    display_name: str
    photo_url: str | None
    prefix: str | None
    is_admin: bool
    is_arbiter: bool
    is_vip: bool
    is_banned: bool
    is_frozen: bool
    # Item 12 — surface the *trust* deposit balance (lock-in capital).
    # ``POST /api/admin/users/:id/trust-deposit`` is the only mutator.
    trust_deposit_balance: MoneyDecimal
    rating: MoneyDecimal
    deals_total: int
    deals_success: int
    last_ip: str | None
    last_login_at: datetime | None
    created_at: datetime


class AdminUserListOut(BaseModel):
    items: list[AdminUserListItem]
    total: int
    page: int
    page_size: int


class AdminUserDetailOut(BaseModel):
    """Full admin view of a user — superset of :class:`UserOut`.

    Includes fields that are deliberately hidden from regular users
    (tg_user_id, IP, login_count, ban/freeze reasons).
    """

    id: int
    tg_user_id: int
    username: str | None
    display_name: str
    photo_url: str | None
    banner_url: str | None
    description: str
    # Item 12 — the trust-deposit balance is the column the public
    # profile reads as ``deposit`` (see
    # ``serializers._common_user_fields``). Written via the
    # ``trust-deposit`` admin endpoint.
    trust_deposit_balance: MoneyDecimal
    rating_auto: MoneyDecimal
    rating_manual: MoneyDecimal | None
    rating_effective: MoneyDecimal
    good: int
    bad: int
    deals_total: int
    deals_success: int
    deals_failed: int
    deals_arbitrage: int
    # Admin-editable "сумма сделок" surfaced as ``deals_sum`` on the
    # public user DTO. Settable via ``POST /admin/users/:id/stats``.
    deals_sum_override: MoneyDecimal
    is_admin: bool
    is_arbiter: bool
    is_vip: bool
    is_banned: bool
    ban_reason: str | None
    is_frozen: bool
    freeze_reason: str | None
    is_anonymous_deals: bool
    is_hidden_profile: bool
    has_pin: bool
    last_ip: str | None
    last_login_at: datetime | None
    # Bumped on the first authenticated API request per
    # ``deps._LAST_LOGIN_DEBOUNCE`` window (5 min), not per-request.
    # Effectively counts "API sessions seen" rather than literal
    # Telegram logins.
    login_count: int
    # Audit v3 A-3 — true distinct-session counter, bumped only when
    # the gap since the previous ping crossed ``deps._SESSION_GAP``
    # (30 min by default).  A user idle on the SPA all day shows up
    # with ``login_count ≈ 96`` but ``sessions_count = 1``; a user
    # who comes back twice (morning + evening) shows ``sessions_count
    # = 2``. Use this column — not ``login_count`` — for DAU/MAU.
    sessions_count: int
    created_at: datetime


class AdminReasonIn(BaseModel):
    """Optional ``{reason}`` body shared by most state-change endpoints.

    User stated reasons are *optional* — server accepts an empty body.
    A reason is logged verbatim into ``admin_audit_log.reason`` and DMed
    to the affected user.
    """

    reason: str | None = None

    @field_validator("reason")
    @classmethod
    def _reason_ok(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        if len(v) > 500:
            raise ValueError("Причина слишком длинная (≤500)")
        return v


class AdminSetRoleIn(BaseModel):
    """Body for ``POST /admin/users/:id/role``.

    Pass any combination of the three role flags. The moderator role
    was dropped from the spec and is not supported here.
    """

    is_admin: bool = False
    is_arbiter: bool = False
    is_vip: bool = False


class AdminSetRatingIn(BaseModel):
    """Body for ``POST /admin/users/:id/rating``.

    ``rating`` is the manual override (0..5 with one decimal). Pass
    ``None`` to clear the override and restore the auto-computed rating.
    """

    rating: float | None = None

    @field_validator("rating")
    @classmethod
    def _rating_ok(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if v < 0 or v > 5:
            raise ValueError("Рейтинг должен быть в диапазоне 0..5")
        return round(v, 1)


class AdminSetStatsIn(BaseModel):
    """Body for ``POST /admin/users/:id/stats``.

    Every field is optional — only provided keys are applied. Negative
    values are rejected because counts/sums don't make sense below
    zero. Rating is *not* part of this schema (see
    :class:`AdminSetRatingIn`) and has no range validation.
    """

    deals_total: int | None = None
    deals_success: int | None = None
    deals_failed: int | None = None
    deals_arbitrage: int | None = None
    good: int | None = None
    bad: int | None = None
    # Admin-editable "сумма сделок" — surfaced as ``deals_sum`` on the
    # public/private user DTOs. ``Decimal`` to match the rest of the
    # money columns (Numeric(28, 8)); negative values rejected by the
    # validator below.
    deals_sum_override: Decimal | None = None

    @field_validator(
        "deals_total",
        "deals_success",
        "deals_failed",
        "deals_arbitrage",
        "good",
        "bad",
        mode="before",
    )
    @classmethod
    def _non_negative_int(cls, v: object) -> int | None:
        return _validate_optional_non_negative_int(v)

    @field_validator("deals_sum_override")
    @classmethod
    def _non_negative_money(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v < 0:
            raise ValueError("Значение не может быть отрицательным")
        return v


class AdminSetTrustDepositIn(BaseModel):
    """Body for ``POST /admin/users/:id/trust-deposit``.

    Sets the user's :attr:`~backend.app.models.User.trust_deposit_balance`
    — the column rendered as ``deposit`` on the public
    ``UserOut`` / ``UserPublicOut`` DTOs.

    The value is *absolute* (the admin types the new total, not a
    delta); negative values are rejected because the trust deposit
    has no spend / withdraw path so a negative balance is
    structurally impossible.
    """

    amount: Decimal
    reason: str | None = None

    @field_validator("amount")
    @classmethod
    def _amount_ok(cls, v: Decimal | float) -> Decimal:
        d = _reject_non_finite_money(v)
        if d is None:
            raise ValueError("Сумма обязательна")
        if d < 0:
            raise ValueError("Значение не может быть отрицательным")
        return d

    @field_validator("reason")
    @classmethod
    def _reason_ok(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        if len(v) > 500:
            raise ValueError("Причина слишком длинная (≤500)")
        return v


class AdminAuditLogOut(BaseModel):
    id: int
    actor_id: int | None
    actor_username: str | None
    action: str
    target_type: str | None
    target_id: int | None
    reason: str | None
    payload: dict | None
    ip: str | None
    created_at: datetime


# ── Admin: deal management (PR-B) ──────────────────────


class AdminDealListItem(BaseModel):
    """Single row in ``GET /api/admin/deals`` listing.

    Contains identity, money, status, timestamps and a small set of
    derived flags (``has_arbitration``, ``has_cancel_request``) so the
    list view can filter and badge without a separate per-row fetch.
    """

    id: int
    status: str
    currency_code: str | None
    # M-3 wire format: ``Decimal`` (not ``MoneyDecimal``) so Pydantic
    # serialises as a JSON string and the admin UI sees full
    # ``Numeric(28, 8)`` precision.  ``MoneyDecimal`` would re-cast to
    # ``float`` and silently drop trailing satoshi on large BTC sums.
    amount: Decimal
    commission_amount: Decimal | None
    buyer_id: int
    buyer_username: str | None
    seller_id: int
    seller_username: str | None
    created_at: datetime
    in_progress_at: datetime | None
    completed_at: datetime | None
    has_arbitration: bool
    has_cancel_request: bool


class AdminDealListOut(BaseModel):
    items: list[AdminDealListItem]
    total: int
    page: int
    page_size: int


class AdminBalanceSnapshot(BaseModel):
    """Per-currency wallet balance + lock state at request time.

    H-1: previously this DTO included the legacy USD ``user.balance``
    column. After the legacy ledger was retired the snapshot is
    purely the per-currency ``UserBalance`` row pair (``amount`` +
    ``locked``); ``currency_code`` is non-null on every live deal.
    """

    user_id: int
    username: str | None
    display_name: str
    currency_code: str | None
    # M-3 wire format — see ``AdminDealListItem.amount`` for rationale.
    amount: Decimal
    locked: Decimal
    total: Decimal


class AdminDealEventItem(BaseModel):
    """One row in the deal's reconstructed event timeline.

    Built from the ``Deal`` row itself (no separate event table). Each
    timestamped column becomes its own item so the timeline UI can show
    a single ordered list without re-deriving anything.
    """

    at: datetime
    # Discriminator for the timeline UI: one of 'created', 'in_progress',
    # 'cancel_request', 'arbitration_started', 'arbitration_resolved',
    # 'completed'. Kept as a free-form ``str`` instead of an Enum because
    # the timeline grows by adding rows, not by changing client code.
    kind: str
    actor: str | None  # 'buyer' | 'seller' | 'admin' | 'arbiter' | None
    description: str


class AdminDealDetailOut(BaseModel):
    """Full admin view of a deal."""

    id: int
    status: str
    description: str
    currency_code: str | None
    # M-3 wire format — see ``AdminDealListItem.amount`` for rationale.
    amount: Decimal
    commission_amount: Decimal | None
    commission_paid: bool = False
    topup_deposit_id: int | None = None
    buyer: AdminBalanceSnapshot
    seller: AdminBalanceSnapshot
    created_at: datetime
    in_progress_at: datetime | None
    completed_at: datetime | None
    cancellation_initiator: str | None
    cancellation_reason: str | None
    cancellation_requested_at: datetime | None
    arbitration_initiator: str | None
    arbitration_reason: str | None
    arbitration_resolved_by_id: int | None
    arbitration_resolved_by_username: str | None
    arbitration_resolution: str | None
    arbitration_resolved_at: datetime | None
    confirm_buyer: bool
    confirm_seller: bool
    events: list[AdminDealEventItem]
    messages: list[DealMessageOut]
    pending_approvals: list[AdminApprovalOut] = Field(default_factory=list)


class AdminApprovalOut(BaseModel):
    id: int
    action: str
    target_type: str
    target_id: int
    status: str
    requested_by_id: int | None
    approved_by_id: int | None = None
    executed_by_id: int | None = None
    currency_code: str | None = None
    amount: Decimal | None = None
    amount_usd_estimate: Decimal | None = None
    reason: str | None = None
    payload: dict[str, Any] | None = None
    created_at: datetime
    approved_at: datetime | None = None
    executed_at: datetime | None = None
    rejected_at: datetime | None = None


class AdminDealActionResult(BaseModel):
    """Generic response after a state-changing admin action on a deal."""

    deal: AdminDealDetailOut
    pending_approval: AdminApprovalOut | None = None


class AdminDealForceOut(BaseModel):
    """Body for ``POST /api/admin/deals/:id/force-release`` and similar.

    Optional ``reason`` is propagated into the audit log and DMs.
    """

    reason: str | None = None
    approval_id: int | None = None

    @field_validator("approval_id", mode="before")
    @classmethod
    def _approval_id_strict_positive(cls, v: object) -> object:
        return _validate_optional_positive_int_id(v, what="ID заявки")

    @field_validator("reason")
    @classmethod
    def _len(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        if len(v) > 500:
            raise ValueError("Причина слишком длинная (≤500)")
        return v


class AdminDealSplitIn(BaseModel):
    """Body for ``POST /api/admin/deals/:id/split``.

    ``buyer_percent`` is the share returned to the buyer; the seller
    gets ``100 - buyer_percent`` of the same locked pot. Commission
    is collected on the platform via the deposit invoice (P10) and
    is *never* refunded — admin-forced splits operate only on the
    locked principal.
    """

    buyer_percent: Decimal
    reason: str | None = None
    approval_id: int | None = None

    @field_validator("approval_id", mode="before")
    @classmethod
    def _approval_id_strict_positive(cls, v: object) -> object:
        return _validate_optional_positive_int_id(v, what="ID заявки")

    @field_validator("buyer_percent")
    @classmethod
    def _percent_ok(cls, v: Decimal | float) -> Decimal:
        d = Decimal(str(v)) if isinstance(v, float) else v
        if d < 0 or d > 100:
            raise ValueError("Доля покупателя должна быть в диапазоне 0..100")
        return d.quantize(Decimal("0.01"))


class AdminDealAssignArbiterIn(BaseModel):
    """Body for ``POST /api/admin/deals/:id/assign-arbiter``.

    ``arbiter_id`` must reference a user with ``is_arbiter=True`` (admins
    are accepted too). Use ``None`` to clear the assignment.
    """

    arbiter_id: int | None = None

    @field_validator("arbiter_id", mode="before")
    @classmethod
    def _arbiter_id_strict_positive(cls, v: object) -> object:
        return _validate_optional_positive_int_id(v, what="ID арбитра")


# ── Admin: arbitration queue (PR-B) ────────────────────


class AdminArbitrationCounters(BaseModel):
    new: int
    in_progress: int
    closed: int


class AdminArbitrationListOut(BaseModel):
    items: list[AdminDealListItem]
    counters: AdminArbitrationCounters
    queue: str  # 'new' | 'in_progress' | 'closed' — echoes the request


# ── Admin: content editing on behalf of users (PR-B) ────


class AdminServiceItemOut(BaseModel):
    id: int
    owner_id: int
    category_id: int
    category_slug: str | None
    title: str
    description: str
    price: MoneyDecimal
    status: str
    ban_reason: str | None
    views: int
    deals_count: int
    deposit: MoneyDecimal
    rating_manual: MoneyDecimal | None
    created_at: datetime


class AdminServiceListOut(BaseModel):
    items: list[AdminServiceItemOut]
    total: int
    page: int
    page_size: int


class AdminServiceUpdateIn(BaseModel):
    """Body for ``POST /api/admin/services/:id``.

    Every field is optional. Negative numeric values are rejected per
    the spec (counts / deposits cannot be < 0). ``rating_manual`` is
    bounded to 0..5 to match the user rating override; pass ``None``
    explicitly with ``clear_rating=true`` to remove it.
    """

    title: str | None = None
    description: str | None = None
    price: Decimal | None = None
    deposit: Decimal | None = None
    views: int | None = None
    deals_count: int | None = None
    rating_manual: Decimal | None = None
    clear_rating: bool = False
    status: Literal["draft", "active", "paused", "banned"] | None = None
    ban_reason: str | None = None

    @field_validator("title")
    @classmethod
    def _title_ok(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Название не может быть пустым")
        if len(v) > 256:
            raise ValueError("Название слишком длинное (≤256)")
        return v

    @field_validator("description")
    @classmethod
    def _description_ok(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if len(v) > 4000:
            raise ValueError("Описание слишком длинное (≤4000)")
        return v

    @field_validator("price", "deposit")
    @classmethod
    def _non_negative_decimal(cls, v: Decimal | float | None) -> Decimal | None:
        if v is None:
            return None
        d = _reject_non_finite_money(v)
        if d is not None and d < 0:
            raise ValueError("Значение не может быть отрицательным")
        return d

    @field_validator("views", "deals_count", mode="before")
    @classmethod
    def _non_negative_int(cls, v: object) -> int | None:
        return _validate_optional_non_negative_int(v)

    @field_validator("rating_manual")
    @classmethod
    def _rating_ok(cls, v: Decimal | float | None) -> Decimal | None:
        if v is None:
            return v
        d = Decimal(str(v)) if isinstance(v, float) else v
        if d < 0 or d > 5:
            raise ValueError("Рейтинг должен быть в диапазоне 0..5")
        return d.quantize(Decimal("0.1"))


class AdminReviewItemOut(BaseModel):
    id: int
    deal_id: int | None
    author_id: int
    author_username: str | None
    target_id: int
    target_username: str | None
    rating: int
    text: str
    created_at: datetime


class AdminReviewListOut(BaseModel):
    items: list[AdminReviewItemOut]
    total: int
    page: int
    page_size: int


class AdminReviewUpsertIn(BaseModel):
    """Body for ``POST /api/admin/reviews`` (create) /
    ``POST /api/admin/reviews/:id`` (edit).

    For create, ``target_id`` and ``author_id`` are required. For edit,
    they are ignored — only ``rating`` and ``text`` can be changed.
    """

    target_id: int | None = None
    author_id: int | None = None
    deal_id: int | None = None
    rating: int
    text: str = ""

    @field_validator("target_id", "author_id", "deal_id", mode="before")
    @classmethod
    def _strict_positive_ids(cls, v: object) -> object:
        return _validate_optional_positive_int_id(v)

    @field_validator("rating", mode="before")
    @classmethod
    def _rating_strict_int(cls, v: object) -> object:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("Рейтинг должен быть целым числом")
        return v

    @field_validator("rating")
    @classmethod
    def _rating_range(cls, v: int) -> int:
        if v < 1 or v > 5:
            raise ValueError("Рейтинг должен быть от 1 до 5")
        return v

    @field_validator("text")
    @classmethod
    def _text_len(cls, v: str) -> str:
        if len(v) > 1024:
            raise ValueError("Текст отзыва слишком длинный (≤1024)")
        return v


class AdminCommentItemOut(BaseModel):
    id: int
    service_id: int
    author_id: int
    author_username: str | None
    text: str
    rating: int | None
    created_at: datetime


class AdminCommentListOut(BaseModel):
    items: list[AdminCommentItemOut]
    total: int
    page: int
    page_size: int


class AdminCommentUpdateIn(BaseModel):
    text: str | None = None
    rating: int | None = None
    clear_rating: bool = False

    @field_validator("text")
    @classmethod
    def _text_len(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Комментарий не может быть пустым")
        if len(v) > 1024:
            raise ValueError("Комментарий слишком длинный (≤1024)")
        return v

    @field_validator("rating", mode="before")
    @classmethod
    def _rating_strict_int(cls, v: object) -> object:
        if v is None:
            return v
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("Оценка должна быть целым числом")
        return v

    @field_validator("rating")
    @classmethod
    def _rating_range(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 1 or v > 5:
            raise ValueError("Оценка должна быть от 1 до 5")
        return v


# ── Admin: wallets / balances (PR-CDE) ─────────────────


class AdminUserBalanceOut(BaseModel):
    """A single ``(user, currency, amount, locked)`` row.

    Returned in admin wallet views and inside :class:`AdminUserWalletOut`.
    ``user_id`` / ``username`` are denormalised so the list page can
    render without a second fetch.
    """

    user_id: int
    username: str | None
    display_name: str
    currency_id: int
    currency_code: str
    currency_name: str
    decimals: int
    # M-3 wire format — see ``AdminDealListItem.amount`` for rationale.
    amount: Decimal
    locked: Decimal
    total: Decimal
    usd_rate: Decimal | None = None
    usd_estimate: Decimal | None = None
    usd_rate_source: str | None = None
    usd_rate_observed_at: datetime | None = None
    updated_at: datetime | None


class AdminWalletListItem(BaseModel):
    """Per-user wallet summary in the admin wallet list."""

    user_id: int
    username: str | None
    display_name: str
    photo_url: str | None
    is_admin: bool
    is_arbiter: bool
    is_vip: bool
    is_banned: bool
    is_frozen: bool
    balances: list[AdminUserBalanceOut]
    total_usd_estimate: Decimal | None = None
    usd_estimate_missing_rates: list[str] = Field(default_factory=list)


class AdminWalletListOut(BaseModel):
    items: list[AdminWalletListItem]
    total: int
    page: int
    page_size: int


class AdminWalletAdjustIn(BaseModel):
    """Body for ``POST /api/admin/wallets/:user_id/adjust``.

    ``amount`` is the *delta* in the asset's native unit. Positive values
    credit, negative debit. ``currency_code`` references the asset; the
    user-balance row is created if absent.

    Reason is optional per the user's directive ("если не указываю просто
    корректирует баланс как я укажу").
    """

    currency_code: str
    amount: Decimal
    reason: str | None = None

    @field_validator("currency_code")
    @classmethod
    def _code_ok(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not v or len(v) > 16:
            raise ValueError("Некорректный код валюты")
        return v

    @field_validator("amount")
    @classmethod
    def _amount_ok(cls, v: Decimal | float) -> Decimal:
        d = _reject_non_finite_money(v)
        if d is None or d == 0:
            raise ValueError("Сумма не может быть равна нулю")
        return d

    @field_validator("reason")
    @classmethod
    def _reason_len(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        if len(v) > 500:
            raise ValueError("Причина слишком длинная (≤500)")
        return v


# ── Admin: deposits queue (PR-CDE) ─────────────────────


class AdminCurrencyRateOut(BaseModel):
    currency_id: int
    currency_code: str
    usd_rate: Decimal
    source: str
    observed_at: datetime
    updated_at: datetime | None = None
    updated_by_id: int | None = None


class AdminCurrencyRateUpsertIn(BaseModel):
    currency_code: str
    usd_rate: Decimal
    source: str = "manual"
    observed_at: datetime | None = None

    @field_validator("currency_code")
    @classmethod
    def _rate_code_ok(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not v or len(v) > 16:
            raise ValueError("Invalid currency code")
        return v

    @field_validator("usd_rate")
    @classmethod
    def _rate_ok(cls, v: Decimal | float) -> Decimal:
        d = _reject_non_finite_money(v)
        if d is None or d <= 0:
            raise ValueError("USD rate must be greater than zero")
        return d

    @field_validator("source")
    @classmethod
    def _source_ok(cls, v: str) -> str:
        v = (v or "manual").strip() or "manual"
        if len(v) > 64:
            raise ValueError("source is too long (<=64)")
        return v


class AdminDepositOut(BaseModel):
    id: int
    user_id: int
    username: str | None
    display_name: str
    currency_code: str
    # M-3 wire format — see ``AdminDealListItem.amount`` for rationale.
    amount: Decimal
    status: str
    provider_invoice_id: str
    pay_url: str
    created_at: datetime
    paid_at: datetime | None


class AdminDepositListOut(BaseModel):
    items: list[AdminDepositOut]
    total: int
    page: int
    page_size: int


# ── Admin: withdrawals queue (PR-CDE) ──────────────────


class AdminWithdrawalOut(BaseModel):
    id: int
    user_id: int
    username: str | None
    display_name: str
    currency_code: str
    # M-3 wire format — see ``AdminDealListItem.amount`` for rationale.
    amount: Decimal
    # ``None`` when the withdrawal was created in CryptoBot Transfer
    # auto-mode (no on-chain address — recipient is the user's
    # ``tg_user_id``). Manual-mode rows always carry the address.
    address: str | None
    status: str
    admin_note: str
    created_at: datetime
    processed_at: datetime | None


class AdminWithdrawalListOut(BaseModel):
    items: list[AdminWithdrawalOut]
    counters: dict[str, int]


class AdminWithdrawalDecisionIn(BaseModel):
    """Body for approve/reject + manual mark-sent on a withdrawal."""

    action: Literal["approve", "reject", "mark_sent"]
    note: str | None = None

    @field_validator("note")
    @classmethod
    def _note_len(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        if len(v) > 500:
            raise ValueError("Комментарий слишком длинный (≤500)")
        return v


# ── Admin: treasury (REMOVED P5) ───────────────────────
#
# P5 — the treasury withdrawal flow and the on-platform commission
# accumulator have been removed entirely. Commission is now collected
# at deal-create time through the wallet provider's invoice (see
# ``services_deals.create_deal_with_topup`` and the P10 flow): the
# platform's CryptoBot / Crystalpay merchant account is now the
# canonical home of accumulated commission, so the per-deal
# ``commission_amount`` accumulator and the ``treasury_withdrawals``
# admin queue are no longer needed. All ``AdminTreasury*`` schemas
# that lived here were dropped; the migration in
# ``backend/alembic/versions/`` drops the corresponding tables.


# ── Admin: settings (PR-CDE) ───────────────────────────


class AdminSettingsOut(BaseModel):
    deal_commission_percent: MoneyDecimal
    vip_commission_percent: MoneyDecimal
    inactivity_pending_confirmation_days: int
    inactivity_pending_cancellation_days: int
    max_active_services_per_user: int
    maintenance_enabled: bool
    maintenance_message: str
    auto_withdraw_enabled: bool
    pending_topup_expiry_hours: int
    pin_reset_price_usd: MoneyDecimal
    faq_stats_badge_enabled: bool
    faq_stats_users: int
    faq_stats_deals: int
    faq_stats_total_usd: MoneyDecimal


class AdminSettingsUpdateIn(BaseModel):
    """Partial update of :class:`AppSettings`.

    Every field is optional. Numeric values must be non-negative
    (commission percentages additionally bounded to ``0..100``).
    """

    deal_commission_percent: Decimal | None = None
    vip_commission_percent: Decimal | None = None
    inactivity_pending_confirmation_days: int | None = None
    inactivity_pending_cancellation_days: int | None = None
    max_active_services_per_user: int | None = None
    maintenance_enabled: bool | None = None
    maintenance_message: str | None = None
    auto_withdraw_enabled: bool | None = None
    pending_topup_expiry_hours: int | None = None
    pin_reset_price_usd: Decimal | None = None
    faq_stats_badge_enabled: bool | None = None
    faq_stats_users: int | None = None
    faq_stats_deals: int | None = None
    faq_stats_total_usd: Decimal | None = None

    @field_validator("deal_commission_percent")
    @classmethod
    def _deal_commission_ok(cls, v: Decimal | float | int | None) -> Decimal | None:
        d = _reject_non_finite_money(v)
        if d is None:
            return None
        if d < 0 or d > 100:
            raise ValueError("Обычная комиссия должна быть в диапазоне 0..100")
        return d.quantize(Decimal("0.01"))

    @field_validator("vip_commission_percent")
    @classmethod
    def _commission_ok(cls, v: Decimal | float | int | None) -> Decimal | None:
        d = _reject_non_finite_money(v)
        if d is None:
            return None
        if d < -1 or d > 100:
            raise ValueError("Комиссия должна быть в диапазоне -1..100")
        return d.quantize(Decimal("0.01"))

    @field_validator(
        "inactivity_pending_confirmation_days",
        "inactivity_pending_cancellation_days",
        "max_active_services_per_user",
        "pending_topup_expiry_hours",
        "faq_stats_users",
        "faq_stats_deals",
        mode="before",
    )
    @classmethod
    def _int_ok(cls, v: object) -> int | None:
        return _validate_optional_non_negative_int(v)

    @field_validator("faq_stats_total_usd")
    @classmethod
    def _faq_stats_total_usd_ok(cls, v: Decimal | float | int | None) -> Decimal | None:
        d = _reject_non_finite_money(v)
        if d is None:
            return None
        if d < 0:
            raise ValueError("Значение не может быть отрицательным")
        return d

    @field_validator("maintenance_message")
    @classmethod
    def _msg_ok(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Сообщение не может быть пустым")
        if len(v) > 1024:
            raise ValueError("Сообщение слишком длинное (≤1024)")
        return v

    @field_validator("pin_reset_price_usd")
    @classmethod
    def _price_ok(cls, v: Decimal | float | int | None) -> Decimal | None:
        if v is None:
            return v
        d = Decimal(str(v))
        if d < 0:
            raise ValueError("Цена не может быть отрицательной")
        return d


# ── Admin: taxonomy (categories + forums) ──────────────


class AdminCategoryOut(BaseModel):
    id: int
    slug: str
    name: str
    icon: str


class AdminCategoryUpsertIn(BaseModel):
    slug: str
    name: str
    icon: str = ""

    @field_validator("slug")
    @classmethod
    def _slug_ok(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if not v:
            raise ValueError("Slug не может быть пустым")
        if len(v) > 64:
            raise ValueError("Slug слишком длинный (≤64)")
        return v

    @field_validator("name")
    @classmethod
    def _name_ok(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Название не может быть пустым")
        if len(v) > 128:
            raise ValueError("Название слишком длинное (≤128)")
        return v

    @field_validator("icon")
    @classmethod
    def _icon_ok(cls, v: str) -> str:
        v = (v or "").strip()
        if len(v) > 64:
            raise ValueError("Иконка слишком длинная (≤64)")
        return v


# ── Currency CRUD (admin) ──────────────────────────────


class AdminCurrencyOut(BaseModel):
    id: int
    code: str
    name: str
    network: str
    icon_url: str
    decimals: int
    # Audit §13.7.2 — surface ``min_deposit`` / ``min_withdraw`` as
    # ``MoneyDecimal`` so the value is computed/compared as ``Decimal``
    # internally and only collapsed to ``float`` at the JSON boundary
    # (same trade-off documented on ``MoneyDecimal`` itself). The
    # underlying column is ``Numeric(28, 8)``; reading it back through
    # ``float`` truncated the last few digits on currencies like SHIB.
    min_deposit: MoneyDecimal
    min_withdraw: MoneyDecimal
    is_active: bool
    sort_order: int
    # Audit §13.7.3 — per-currency anchored regex applied to user-
    # supplied payout addresses in ``services_wallet.create_withdrawal``.
    # Echoed back here so the admin UI can round-trip the value through
    # the upsert endpoint without losing it.
    address_regex: str = ""
    # Mirrors :attr:`backend.app.models.Currency.kind` — ``"crypto"``
    # (default) or ``"fiat"`` — so the admin currency editor can
    # surface the kind alongside the rest of the row.
    kind: str = "crypto"


class AdminCurrencyUpsertIn(BaseModel):
    code: str
    name: str | None = None
    network: str | None = None
    icon_url: str | None = None
    decimals: int | None = None
    # Audit §13.7.2 — ``Decimal`` end-to-end so an admin who enters
    # ``0.123456789012345678`` doesn't silently lose precision through
    # a float64 round-trip on the way into the ``Numeric(28, 8)`` DB
    # column. ``MoneyDecimal`` would also work but the wire shape on
    # the *input* side is already ``Decimal`` (pydantic v2 coerces JSON
    # numbers natively); ``Decimal | None`` keeps the contract symmetric
    # with ``ServiceUpdate.price``.
    min_deposit: Decimal | None = None
    min_withdraw: Decimal | None = None
    is_active: bool | None = None
    sort_order: int | None = None
    # Audit §13.7.3 — allow the admin to set the per-currency address
    # regex through the upsert endpoint instead of relying on the
    # ``d9f1c3a8e205_currencies_address_regex`` back-fill migration +
    # ``seed.CURRENCY_ADDRESS_REGEX`` for new currencies. Empty string
    # / ``None`` keep the deliberate "validation disabled" fallback
    # documented in ``services_wallet.create_withdrawal``; any non-empty
    # value is compiled below to reject malformed patterns at the API
    # boundary instead of crashing at withdrawal time.
    address_regex: str | None = None
    # ``"crypto"`` (default) or ``"fiat"``. Admin-editable so a
    # newly-added asset can be classified without an out-of-band
    # SQL update.
    kind: Literal["crypto", "fiat"] | None = None

    @field_validator("code")
    @classmethod
    def _code_ok(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not v or len(v) > 16:
            raise ValueError("Некорректный код валюты")
        return v

    @field_validator("decimals")
    @classmethod
    def _decimals_ok(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 0 or v > 18:
            raise ValueError("decimals должно быть 0..18")
        return v

    @field_validator("min_deposit", "min_withdraw")
    @classmethod
    def _min_ok(cls, v: Decimal | float | int | None) -> Decimal | None:
        # Audit §13.7.2 — share the finiteness + non-negative guard with
        # every other money field instead of comparing the raw float.
        result = _reject_non_finite_money(v)
        if result is not None and result < 0:
            raise ValueError("Значение не может быть отрицательным")
        return result

    @field_validator("address_regex")
    @classmethod
    def _address_regex_ok(cls, v: str | None) -> str | None:
        # Audit §13.7.3 — sanity-check the regex compiles. ``None`` /
        # empty string mean "don't change" / "validation disabled";
        # any other value must be a valid Python regex so the
        # ``re.fullmatch`` call in ``services_wallet.create_withdrawal``
        # cannot crash at withdrawal time.
        if v is None:
            return v
        if v == "":
            return v
        if len(v) > 1024:
            raise ValueError("address_regex слишком длинный (≤1024)")
        # Audit L-4 — the regex column is admin-controlled and runs
        # ``re.fullmatch(address_regex, address)`` per withdrawal in
        # ``services_wallet.create_withdrawal``. Python's ``re`` has
        # no per-match timeout, so a regex with catastrophic
        # backtracking (``^(a+)+$``, ``(.*?)+$``, …) plus a long
        # user-supplied address can pin a worker thread indefinitely.
        # Exploitation requires admin access (already-privileged
        # threat), but the blast radius is the whole event loop on
        # that worker — every other request stalls.
        #
        # We reject the two ReDoS-canonical shapes at write time so
        # an inattentive admin can't paste a textbook bad pattern.
        # The denylist is intentionally narrow (not a full regex
        # static analyser — that's its own can of worms); it catches
        # the well-known cases without blocking legitimate
        # ``^[A-Za-z0-9]{34}$``-style addresses.
        nested_quantifier = re.compile(
            r"""
            \(            # opening group
            [^()]*        # body without nesting (keeps the check linear)
            [+*]          # inner quantifier
            \)            # close group
            [+*]          # quantifier on the group itself  ← the ReDoS shape
            """,
            re.VERBOSE,
        )
        if nested_quantifier.search(v):
            raise ValueError(
                "address_regex содержит вложенные квантификаторы (риск ReDoS); "
                "используйте простые шаблоны вида ^[A-Za-z0-9]{...}$"
            )
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"Невалидный address_regex: {exc}") from exc
        return v


# ── Admin: broadcasts (PR-CDE) ─────────────────────────


class AdminBroadcastOut(BaseModel):
    id: int
    actor_id: int
    actor_username: str | None
    title: str
    body: str
    deeplink: str | None
    audience_role: str | None
    audience_active_days: int | None
    audience_min_deals: int | None
    # A-6 — temporal + language cohort filters. ``None`` means "unset"
    # (i.e. the row passes that filter unconditionally); the admin
    # composer round-trips these so historical broadcasts remain
    # inspectable.
    audience_created_after: datetime | None
    audience_created_before: datetime | None
    audience_language: str | None
    dispatch_inapp: bool
    dispatch_dm: bool
    status: str
    total_recipients: int
    delivered_count: int
    failed_count: int
    scheduled_at: datetime | None
    sent_at: datetime | None
    created_at: datetime


class AdminBroadcastListOut(BaseModel):
    items: list[AdminBroadcastOut]
    total: int
    page: int
    page_size: int


class AdminBroadcastCreateIn(BaseModel):
    """Body for ``POST /api/admin/broadcasts``.

    Audience filters compose with AND. All optional; if every filter is
    omitted the broadcast goes to *every* user.
    """

    title: str = ""
    body: str
    deeplink: str | None = None
    audience_role: Literal["admin", "arbiter", "vip", "regular"] | None = None
    audience_active_days: int | None = None
    audience_min_deals: int | None = None
    # A-6 — temporal + language cohort filters. See ``Broadcast`` model
    # docstring for semantics; validators below enforce ordering /
    # length so the admin composer can't smuggle a 1 MiB language tag
    # past the audience builder.
    audience_created_after: datetime | None = None
    audience_created_before: datetime | None = None
    audience_language: str | None = None
    dispatch_inapp: bool = True
    dispatch_dm: bool = False
    scheduled_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def _title_len(cls, v: str) -> str:
        if len(v) > 256:
            raise ValueError("Заголовок слишком длинный (≤256)")
        return v

    @field_validator("body")
    @classmethod
    def _body_ok(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Текст сообщения не может быть пустым")
        if len(v) > 4096:
            raise ValueError("Текст слишком длинный (≤4096)")
        return v

    @field_validator("deeplink")
    @classmethod
    def _deeplink_ok(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        if len(v) > 256:
            raise ValueError("Ссылка слишком длинная (≤256)")
        # M-12: the broadcast DM flow used to ``html.escape`` this
        # value before appending it to the message body, which
        # rewrote any ``?a=1&b=2`` query string into
        # ``?a=1&amp;b=2`` and broke Telegram's URL auto-linking.
        # Validating the scheme up-front lets the DM dispatcher
        # confidently wrap the link in a proper ``<a href="...">``
        # tag (with attribute escaping only) downstream. Allowed
        # schemes mirror the public ForumOut URL validator
        # (``https://``) plus ``tg://`` for in-app deep links.
        low = v.lower()
        if not (low.startswith("https://") or low.startswith("tg://")):
            raise ValueError("Ссылка должна начинаться с https:// или tg://")
        return v

    @field_validator("audience_active_days", "audience_min_deals")
    @classmethod
    def _int_ok(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 0:
            raise ValueError("Значение не может быть отрицательным")
        return v

    @field_validator("audience_language")
    @classmethod
    def _language_ok(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # Normalise to the same lowercase / trimmed shape we persist on
        # ``users.language_code`` so an admin entering ``"RU"`` matches
        # users whose Telegram client reported ``"ru"``.
        v = v.strip().lower()
        if not v:
            return None
        if len(v) > 16:
            raise ValueError("Языковой код слишком длинный (≤16)")
        # Telegram tags are alphanumerics + ``-`` only; reject anything
        # else so an admin can't drop a SQL fragment into the filter.
        for ch in v:
            if not (ch.isalnum() or ch == "-"):
                raise ValueError("Языковой код содержит недопустимые символы")
        return v

    @model_validator(mode="after")
    def _validate_audience_window(self) -> AdminBroadcastCreateIn:
        # A-6 — guard the obvious caller mistake (``created_after`` past
        # ``created_before``) at the edge. The audience-builder would
        # otherwise quietly emit ``0`` recipients and the admin would
        # wonder why their broadcast went nowhere.
        if (
            self.audience_created_after is not None
            and self.audience_created_before is not None
            and self.audience_created_after > self.audience_created_before
        ):
            raise ValueError(
                "Окно регистрации задано наоборот: audience_created_after > audience_created_before"
            )
        return self


class AdminBroadcastPreviewOut(BaseModel):
    """Result of ``POST /api/admin/broadcasts/preview``."""

    total_recipients: int


# ── Admin: analytics (PR-CDE) ──────────────────────────


class AdminAnalyticsKpiOut(BaseModel):
    dau: int
    wau: int
    mau: int
    new_users_24h: int
    new_users_7d: int
    deals_24h: int
    deals_7d: int
    deals_volume_usd_30d: float
    open_arbitration: int
    pending_withdrawals: int


class AdminAnalyticsSeriesPoint(BaseModel):
    date: str  # ISO date (YYYY-MM-DD)
    value: float


class AdminAnalyticsSeriesOut(BaseModel):
    deals_count_30d: list[AdminAnalyticsSeriesPoint]
    deals_volume_30d: list[AdminAnalyticsSeriesPoint]
    new_users_30d: list[AdminAnalyticsSeriesPoint]
    deposits_30d: list[AdminAnalyticsSeriesPoint]
    withdrawals_30d: list[AdminAnalyticsSeriesPoint]


class AdminAnalyticsTopUserOut(BaseModel):
    user_id: int
    username: str | None
    display_name: str
    # Audit §4.3 — top sellers/buyers aggregate ``Deal.amount`` (a
    # ``Numeric(28, 8)`` column) so the lossless wire shape is
    # ``MoneyDecimal`` (Decimal internally, float on JSON to keep the
    # frontend contract identical to the rest of the API). Top
    # arbiters use the same field for a row count, which Pydantic
    # coerces from ``int`` to ``Decimal`` without loss.
    value: MoneyDecimal


class AdminAnalyticsTopListsOut(BaseModel):
    top_sellers: list[AdminAnalyticsTopUserOut]
    top_buyers: list[AdminAnalyticsTopUserOut]
    top_arbiters: list[AdminAnalyticsTopUserOut]


# ── Admin: system (PR-CDE) ─────────────────────────────


class OperationalAlertOut(BaseModel):
    name: str
    severity: Literal["info", "warning", "critical"]
    count: int
    detail: str


class AdminSystemStatusOut(BaseModel):
    db_ok: bool
    db_latency_ms: float | None
    redis_ok: bool
    redis_latency_ms: float | None
    cryptobot_configured: bool
    bot_configured: bool
    backend_version: str
    started_at: datetime | None
    uptime_seconds: float
    alerts: list[OperationalAlertOut] = Field(default_factory=list)


# ── Admin: 2FA (PR-CDE) ────────────────────────────────


class Admin2faSetupOut(BaseModel):
    """Returned by ``POST /api/admin/2fa/setup``.

    ``secret`` is the base32-encoded shared secret; ``otpauth_url`` is
    the ``otpauth://`` URI compatible with Google Authenticator / 1Password.
    The secret is *not* persisted until the admin confirms a code via
    ``POST /api/admin/2fa/enable``.
    """

    secret: str
    otpauth_url: str


class Admin2faConfirmIn(BaseModel):
    secret: str
    code: str
    # Review pass 3 — when rotating an already-enabled 2FA, the caller
    # must prove ownership of the *current* secret by also sending its
    # code. Without this, a stolen admin session could silently swap
    # the 2FA secret to one the attacker controls. Optional on first
    # enrolment (no previous secret to verify).
    current_code: str | None = None

    @field_validator("secret")
    @classmethod
    def _secret_ok(cls, v: str) -> str:
        v = (v or "").strip()
        if not v or len(v) < 16 or len(v) > 64:
            raise ValueError("Некорректный секрет")
        return v

    @field_validator("code")
    @classmethod
    def _code_ok(cls, v: str) -> str:
        v = (v or "").strip()
        if not v.isdigit() or len(v) not in (6, 8):
            raise ValueError("Код должен состоять из 6 или 8 цифр")
        return v

    @field_validator("current_code")
    @classmethod
    def _current_code_ok(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v.isdigit() or len(v) not in (6, 8):
            raise ValueError("Код должен состоять из 6 или 8 цифр")
        return v


class Admin2faStatusOut(BaseModel):
    enabled: bool


class Admin2faVerifyIn(BaseModel):
    code: str

    @field_validator("code")
    @classmethod
    def _code_ok(cls, v: str) -> str:
        v = (v or "").strip()
        if not v.isdigit() or len(v) not in (6, 8):
            raise ValueError("Код должен состоять из 6 или 8 цифр")
        return v


class Admin2faSessionOut(BaseModel):
    """Response of ``POST /api/admin/2fa/session``.

    Mirrors :class:`PinTokenOut` for the 24h TOTP-session JWT — the
    frontend caches both ``token`` and ``expires_at`` in
    localStorage and replays the token on every admin request via
    the ``X-Totp-Session`` header for the lifetime of the session.
    """

    token: str
    expires_at: datetime


# ── Admin: audit log (PR-CDE) ──────────────────────────


class AdminAuditLogListOut(BaseModel):
    items: list[AdminAuditLogOut]
    total: int
    page: int
    page_size: int
