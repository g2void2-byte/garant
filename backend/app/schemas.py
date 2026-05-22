from __future__ import annotations

import json
import math
import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer, field_validator, model_validator

from .models import PayCommission

# H-1: internal calculations use ``Decimal`` for precision, but the
# JSON wire format emits a plain number (``float``) so the frontend
# (JavaScript) can consume values without a string→number parse step.
MoneyDecimal = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float)]

# ── Users ──────────────────────────────────────────────


class ForumOut(BaseModel):
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
        # Comment 36 (audit v9): forum links — whitelist ``https://`` only
        # (``https://t.me/`` is a subset). ``http://`` was downgrade-friendly
        # and ``tg://`` lets a forum entry deep-link straight into Telegram
        # clients without an explicit https handoff; both are dropped.
        v = (v or "").strip()
        if not v:
            raise ValueError("Ссылка не может быть пустой")
        if len(v) > 512:
            raise ValueError("Ссылка слишком длинная")
        low = v.lower()
        if not low.startswith("https://"):
            raise ValueError("Ссылка должна начинаться с https://")
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
    forums: list[ForumOut] | None = None
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
        # Comment 35 (audit v9): drop ``http://`` from the whitelist.
        # Plaintext avatar URLs were a downgrade vector inside a TMA that
        # otherwise only emits https resources; ``/media/...`` is the
        # self-hosted path served by the backend.
        if v is None or v == "":
            return v
        v = v.strip()
        if len(v) > 1024:
            raise ValueError("Ссылка на фото слишком длинная")
        low = v.lower()
        if not (low.startswith("https://") or low.startswith("/media/")):
            raise ValueError("Фото должно быть https:// или /media/... ссылкой")
        return v

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
        # Comment 35 (audit v9): drop ``http://`` from the whitelist.
        # ``/media/...`` is allowed so admins can pin a self-hosted
        # banner the same way they do for avatars.
        if v is None or v == "":
            return v
        v = v.strip()
        if len(v) > 1024:
            raise ValueError("Ссылка на баннер слишком длинная")
        low = v.lower()
        if not (low.startswith("https://") or low.startswith("/media/")):
            raise ValueError("Баннер должен быть https:// или /media/... ссылкой")
        return v

    @field_validator("forums")
    @classmethod
    def _forums_ok(cls, v: list[ForumOut] | None) -> list[ForumOut] | None:
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
    # L-1: ``gt=0`` matches the explicit ``if amt <= 0`` guard in
    # ``services_deals.create_deal``. The validator below additionally
    # rejects ``NaN``/``±inf`` JSON values that bypass the ``gt=0``
    # comparison (``NaN > 0`` is ``False`` — still rejected by
    # ``Field(gt=0)`` — but ``+inf > 0`` is ``True``, which would slip
    # through and break downstream ``Decimal(str(amount))``
    # conversion).
    amount: Decimal = Field(gt=0)
    description: str = ""
    # H-2: canonical field with correct spelling.
    pay_commission: PayCommission = PayCommission.buyer
    # H-2: deprecated alias for backward-compatible JSON input.
    pay_comission: PayCommission | None = Field(default=None, exclude=True)
    currency_code: str = "USDT"
    # Buyer's preferred upstream invoice provider; persisted on the
    # :class:`backend.app.models.Deal` row for future invoice-driven
    # escrow flows. ``"cryptobot"`` keeps legacy clients (no
    # ``payment_provider`` on the wire) backwards-compatible.
    payment_provider: Literal["cryptobot", "crystalpay"] = "cryptobot"

    @model_validator(mode="before")
    @classmethod
    def _migrate_pay_comission(cls, values: dict) -> dict:  # type: ignore[override]
        """Accept the legacy ``pay_comission`` key and copy it to ``pay_commission``."""
        if isinstance(values, dict):
            legacy = values.get("pay_comission")
            if legacy is not None and "pay_commission" not in values:
                values["pay_commission"] = legacy
        return values

    @field_validator("amount")
    @classmethod
    def _amount_finite(cls, v: Decimal | float) -> Decimal:
        result = _reject_non_finite_money(v)
        return result if result is not None else Decimal(0)

    @field_validator("description")
    @classmethod
    def _description_ok(cls, v: str) -> str:
        return _validate_description(v) or ""


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
    description: str
    # H-2: both spellings emitted for backward compat; canonical is
    # ``pay_commission``.
    pay_commission: str
    pay_comission: str  # deprecated alias
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
    address: str

    @field_validator("amount")
    @classmethod
    def positive(cls, v: Decimal | float) -> Decimal:
        result = _reject_non_finite_money(v)
        if result is None or result <= 0:
            raise ValueError("Сумма должна быть больше нуля")
        return result

    @field_validator("address")
    @classmethod
    def strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Адрес не может быть пустым")
        return v


class WalletWithdrawalOut(BaseModel):
    id: int
    currency: CurrencyOut
    amount: MoneyDecimal
    address: str
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
    deposit_total: MoneyDecimal
    # Item 12 — surface the *trust* deposit balance alongside
    # ``deposit_total`` (the admin-editable lifetime aggregate) so
    # the admin list can disambiguate "how much trust capital this
    # user has locked in" from "how much they have ever deposited".
    # The two columns are independent and the new
    # ``POST /api/admin/users/:id/trust-deposit`` endpoint writes
    # this one; the legacy ``POST /api/admin/users/:id/stats`` keeps
    # writing ``deposit_total``.
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
    deposit_total: MoneyDecimal
    # Item 12 — the trust-deposit balance is the column the public
    # profile reads as ``deposit`` (see
    # ``serializers._common_user_fields``). Surfaced here so the
    # admin panel can show both numbers side-by-side and write the
    # right one via the new ``trust-deposit`` endpoint.
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
    deposit_total: Decimal | None = None

    @field_validator(
        "deals_total",
        "deals_success",
        "deals_failed",
        "deals_arbitrage",
        "good",
        "bad",
    )
    @classmethod
    def _non_negative_int(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("Значение не может быть отрицательным")
        return v

    @field_validator("deposit_total")
    @classmethod
    def _non_negative_decimal(cls, v: Decimal | float | None) -> Decimal | None:
        if v is None:
            return None
        d = _reject_non_finite_money(v)
        if d is not None and d < 0:
            raise ValueError("Значение не может быть отрицательным")
        return d


class AdminSetTrustDepositIn(BaseModel):
    """Body for ``POST /admin/users/:id/trust-deposit``.

    Sets the user's :attr:`~backend.app.models.User.trust_deposit_balance`
    — the column rendered as ``deposit`` on the public
    ``UserOut`` / ``UserPublicOut`` DTOs. Distinct from
    ``AdminSetStatsIn.deposit_total`` which edits the admin-only
    lifetime aggregate.

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
    pay_commission: str
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
    pay_commission: str
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


class AdminDealActionResult(BaseModel):
    """Generic response after a state-changing admin action on a deal."""

    deal: AdminDealDetailOut


class AdminDealForceOut(BaseModel):
    """Body for ``POST /api/admin/deals/:id/force-release`` and similar.

    Optional ``reason`` is propagated into the audit log and DMs.
    """

    reason: str | None = None

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
    gets ``100 - buyer_percent`` of the same locked pot. The commission
    component (when ``pay_commission=buyer``) is *always* retained by
    the platform regardless of split — admin-forced splits do not give
    commission back to either party.
    """

    buyer_percent: Decimal
    reason: str | None = None

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

    @field_validator("views", "deals_count")
    @classmethod
    def _non_negative_int(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("Значение не может быть отрицательным")
        return v

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
    # Audit §5.4 — this is **not** a real USD valuation. The field is a
    # naive sum of every per-currency ``total`` (``amount + locked``)
    # treating each unit as 1 USD, because the admin panel doesn't have
    # a price oracle wired up. Holding 1 BTC therefore reports
    # ``total_usd_estimate=1``, not ~70 000. The admin UI must label
    # the column as an approximation; do NOT use it for accounting.
    # M-3 wire format — see ``AdminDealListItem.amount`` for rationale.
    total_usd_estimate: Decimal


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
    address: str
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


# ── Admin: treasury (PR-CDE) ───────────────────────────


class AdminTreasuryBalanceOut(BaseModel):
    """Per-currency commission accumulator.

    ``accrued`` sums up ``commission_amount`` on every completed deal in
    this currency; ``withdrawn`` subtracts the sum of successful
    ``treasury_withdrawals`` rows. ``available`` is the diff and the
    only amount the admin can withdraw.
    """

    currency_id: int
    currency_code: str
    currency_name: str
    decimals: int
    # M-3 wire format — see ``AdminDealListItem.amount`` for rationale.
    accrued: Decimal
    withdrawn: Decimal
    available: Decimal


class AdminTreasuryOverviewOut(BaseModel):
    balances: list[AdminTreasuryBalanceOut]
    total_withdrawals: int


class AdminTreasuryWithdrawIn(BaseModel):
    """Body for ``POST /api/admin/treasury/withdraw``.

    Requires the ``X-Totp-Code`` header (validated by a dependency) and
    ``confirm=true`` to satisfy the double-confirm gate.
    """

    currency_code: str
    amount: Decimal
    address: str
    confirm: bool = False
    note: str | None = None

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
        if d is None or d <= 0:
            raise ValueError("Сумма должна быть положительной")
        return d

    @field_validator("address")
    @classmethod
    def _address_ok(cls, v: str) -> str:
        # ``CryptoPay.transfer`` only accepts a Telegram ``user_id`` (a
        # signed 64-bit integer); wallet addresses are not a thing on
        # the CryptoBot side. Pre-fix this validator accepted any
        # non-empty ≤256-char string, which let the handler silently
        # fall back to ``admin.tg_user_id`` when ``isdigit()`` was
        # false — see the comment on the call site in
        # ``routers/admin/treasury.py``. Force-rejecting non-digit
        # input at the schema makes the silent self-payout codepath
        # unreachable.
        v = (v or "").strip()
        if not v:
            raise ValueError("Адрес не может быть пустым")
        if len(v) > 32:
            # 19 digits is enough for the full signed-int64 range,
            # 32 leaves slack for a sign / formatting quirk without
            # accepting arbitrary blobs.
            raise ValueError("user_id слишком длинный (≤32 символов)")
        if not v.isdigit():
            raise ValueError(
                "Адрес должен быть Telegram user_id (только цифры). "
                "CryptoBot не поддерживает wallet-адреса в transfer API."
            )
        try:
            n = int(v)
        except ValueError as e:
            raise ValueError("user_id должен быть числом") from e
        if n <= 0:
            raise ValueError("user_id должен быть положительным")
        if n > (1 << 63) - 1:
            raise ValueError("user_id вне диапазона int64")
        return v


class AdminTreasuryWithdrawOut(BaseModel):
    id: int
    actor_id: int
    currency_code: str
    # M-3 wire format — see ``AdminDealListItem.amount`` for rationale.
    amount: Decimal
    address: str
    status: str
    note: str
    cryptobot_transfer_id: str | None
    created_at: datetime


class AdminTreasuryMarkSentIn(BaseModel):
    """Body for ``POST /api/admin/treasury/{withdrawal_id}/mark_sent``.

    Manual reconciliation path for treasury rows stuck at ``pending``:
    the CryptoBot transfer actually went through in Phase 2 of
    ``treasury_withdraw`` but Phase 3 failed to commit (network glitch,
    crash, etc.), leaving the row mid-flight. The operator verifies
    the transfer succeeded on CryptoBot's side (via their dashboard
    or the ``spend_id=treas:{row.id}`` lookup), then calls this
    endpoint to advance the row to ``status="sent"``.

    Mirrors ``WalletWithdrawAdminDecideIn(action="mark_sent")`` in
    ``routers/admin/withdrawals.py``.
    """

    confirm: bool = False
    cryptobot_transfer_id: str | None = None
    note: str | None = None

    @field_validator("cryptobot_transfer_id")
    @classmethod
    def _transfer_id_ok(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        # CryptoBot returns a numeric ``transfer_id`` (its own auto-
        # increment id, currently fits int64). Reject anything that
        # isn't a string of digits so the audit row stays grep-able
        # and the reconciliation never silently records garbage.
        if not v.isdigit():
            raise ValueError("cryptobot_transfer_id должен быть числом")
        if len(v) > 32:
            raise ValueError("cryptobot_transfer_id слишком длинный")
        return v


class AdminTreasuryReconcileIn(BaseModel):
    """Body for ``POST /api/admin/treasury/{withdrawal_id}/reconcile``.

    Audit §4.19 — automated reconciliation path for ``pending`` rows
    stuck after a Phase 2 → Phase 3 crash. Unlike ``mark_sent`` (which
    trusts the operator's claim that CryptoBot processed the
    transfer), this endpoint queries CryptoBot's ``getTransfers``
    API by the row's ``spend_id`` and updates the status from the
    authoritative source — flipping to ``sent`` if the transfer
    landed and surfacing a 404 (without mutating the row) if it
    didn't, so the operator can choose whether to retry by issuing
    a fresh withdrawal or close the row out manually.
    """

    confirm: bool = False
    note: str | None = None


class AdminTreasuryReconcileOut(BaseModel):
    """Response for the treasury reconcile endpoint.

    ``status`` mirrors the row's new value (always ``sent`` on the
    success path; the endpoint 404s instead of returning ``failed``
    so a missing CryptoBot transfer never silently buries the row).
    ``withdrawal`` carries the canonical ``TreasuryWithdrawal`` shape
    so the admin UI can refresh from the same payload.
    """

    withdrawal: AdminTreasuryWithdrawOut
    cryptobot_transfer_id: str | None


# ── Admin: settings (PR-CDE) ───────────────────────────


class AdminSettingsOut(BaseModel):
    deal_commission_percent: MoneyDecimal
    invoice_commission_percent: MoneyDecimal
    vip_commission_percent: MoneyDecimal
    min_deposit: MoneyDecimal
    min_withdraw: MoneyDecimal
    inactivity_pending_confirmation_days: int
    inactivity_pending_cancellation_days: int
    max_active_services_per_user: int
    maintenance_enabled: bool
    maintenance_message: str
    auto_withdraw_enabled: bool


class AdminSettingsUpdateIn(BaseModel):
    """Partial update of :class:`AppSettings`.

    Every field is optional. Numeric values must be non-negative
    (commission percentages additionally bounded to ``0..100``).
    """

    deal_commission_percent: Decimal | None = None
    invoice_commission_percent: Decimal | None = None
    vip_commission_percent: Decimal | None = None
    min_deposit: Decimal | None = None
    min_withdraw: Decimal | None = None
    inactivity_pending_confirmation_days: int | None = None
    inactivity_pending_cancellation_days: int | None = None
    max_active_services_per_user: int | None = None
    maintenance_enabled: bool | None = None
    maintenance_message: str | None = None
    auto_withdraw_enabled: bool | None = None

    @field_validator(
        "deal_commission_percent",
        "invoice_commission_percent",
        "vip_commission_percent",
    )
    @classmethod
    def _commission_ok(cls, v: Decimal | float | None) -> Decimal | None:
        if v is None:
            return v
        d = Decimal(str(v)) if isinstance(v, float) else v
        if d < -1 or d > 100:
            raise ValueError("Комиссия должна быть в диапазоне -1..100")
        return d.quantize(Decimal("0.01"))

    @field_validator(
        "min_deposit",
        "min_withdraw",
    )
    @classmethod
    def _min_ok(cls, v: Decimal | float | None) -> Decimal | None:
        if v is None:
            return v
        d = _reject_non_finite_money(v)
        if d is not None and d < 0:
            raise ValueError("Значение не может быть отрицательным")
        return d

    @field_validator(
        "inactivity_pending_confirmation_days",
        "inactivity_pending_cancellation_days",
        "max_active_services_per_user",
    )
    @classmethod
    def _int_ok(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 0:
            raise ValueError("Значение не может быть отрицательным")
        return v

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
