from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

from .models import PayCommission

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
        v = (v or "").strip()
        if not v:
            raise ValueError("Ссылка не может быть пустой")
        if len(v) > 512:
            raise ValueError("Ссылка слишком длинная")
        low = v.lower()
        if not (
            low.startswith("http://")
            or low.startswith("https://")
            or low.startswith("tg://")
            or low.startswith("https://t.me/")
        ):
            raise ValueError("Ссылка должна начинаться с http(s):// или t.me/")
        return v


class UserOut(BaseModel):
    id: int
    user_id: int
    username: str | None
    display_name: str
    photo_url: str | None
    banner_url: str | None
    balance: float
    deposit: float
    description: str
    prefix: str | None
    is_admin: bool
    is_moderator: bool = False
    is_arbiter: bool
    is_vip: bool = False
    is_banned: bool = False
    is_frozen: bool = False
    admin: int
    good: int
    bad: int
    rating: float
    reviews_count: int
    deals_count: int
    deals_sum: float
    online: bool
    forums: list[ForumOut]
    dm_deals: bool = True
    dm_deposits: bool = True
    dm_system: bool = True
    is_anonymous_deals: bool = False
    is_hidden_profile: bool = False


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

    @field_validator("photo_url")
    @classmethod
    def _photo_url_ok(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        v = v.strip()
        if len(v) > 1024:
            raise ValueError("Ссылка на фото слишком длинная")
        low = v.lower()
        if not (
            low.startswith("http://") or low.startswith("https://") or low.startswith("/media/")
        ):
            raise ValueError("Фото должно быть http(s):// или /media/... ссылкой")
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
        if v is None or v == "":
            return v
        v = v.strip()
        if len(v) > 1024:
            raise ValueError("Ссылка на баннер слишком длинная")
        low = v.lower()
        if not (low.startswith("http://") or low.startswith("https://")):
            raise ValueError("Баннер должен быть http(s):// ссылкой")
        return v

    @field_validator("forums")
    @classmethod
    def _forums_ok(cls, v: list[ForumOut] | None) -> list[ForumOut] | None:
        if v is None:
            return v
        if len(v) > 10:
            raise ValueError("Слишком много форумов (≤10)")
        return v


# ── Categories ─────────────────────────────────────────


class CategoryOut(BaseModel):
    id: int
    slug: str
    name: str
    icon_key: str
    services_count: int


# ── Services ───────────────────────────────────────────


class ServiceOut(BaseModel):
    id: int
    owner_username: str | None
    title: str
    description: str
    price: float
    currency: str
    status: str
    category: CategoryOut
    created_at: datetime | None


class ServiceCreate(BaseModel):
    category_slug: str
    title: str
    description: str = ""
    price: float = 0


class ServiceUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    price: float | None = None
    status: str | None = None  # draft / active / paused (banned only via admin)


class ServiceModerationDecision(BaseModel):
    action: str  # "ban" | "unban"
    reason: str = ""


class ServiceOwnerOut(BaseModel):
    """Owner card embedded in :class:`ServiceDetailOut`."""

    id: int
    username: str | None
    display_name: str
    photo_url: str | None
    rating: float
    deals_count: int
    good: int
    bad: int
    is_admin: bool
    is_moderator: bool = False
    is_arbiter: bool


class ServiceDetailOut(ServiceOut):
    owner: ServiceOwnerOut | None
    comments_count: int
    rating_avg: float | None
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
    role: str
    sum: float
    description: str = ""
    pay_comission: PayCommission = PayCommission.buyer
    currency_code: str = "USDT"


class DealCancelRequest(BaseModel):
    reason: str = ""


class DealArbitrationRequest(BaseModel):
    reason: str = ""


class DealResolveRequest(BaseModel):
    winner: str  # "buyer" or "seller"
    note: str = ""

    @field_validator("winner")
    @classmethod
    def winner_valid(cls, v: str) -> str:
        if v not in ("buyer", "seller"):
            raise ValueError("winner должен быть 'buyer' или 'seller'")
        return v


class DealOut(BaseModel):
    id: int
    buyer: str | None
    seller: str | None
    sum: float
    description: str
    pay_comission: str
    status: str
    confirm_buyer: bool
    confirm_seller: bool
    role: str
    created_at: datetime | None
    # PR-3 — multi-currency + state-machine extras.
    currency_code: str | None = None
    amount: float | None = None
    commission_amount: float | None = None
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


class InvoiceCreateReq(BaseModel):
    amount: float


class InvoiceOut(BaseModel):
    invoice_id: str
    pay_url: str
    amount: float
    asset: str


class InvoiceStatusOut(BaseModel):
    id: int
    amount: float
    status: str
    created_at: datetime
    paid_at: datetime | None


class DepositReq(BaseModel):
    amount: float


# ── Wallet (multi-currency) ────────────────────────────


class CurrencyOut(BaseModel):
    id: int
    code: str
    name: str
    network: str
    icon_url: str
    decimals: int
    min_deposit: float
    min_withdraw: float


class WalletBalanceOut(BaseModel):
    currency: CurrencyOut
    amount: float
    locked: float
    total: float
    updated_at: datetime | None


class WalletDepositCreateReq(BaseModel):
    currency_code: str
    amount: float

    @field_validator("amount")
    @classmethod
    def positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Сумма должна быть больше нуля")
        return v


class WalletDepositOut(BaseModel):
    id: int
    currency: CurrencyOut
    amount: float
    status: str
    pay_url: str
    invoice_id: str
    created_at: datetime
    paid_at: datetime | None


class WalletWithdrawCreateReq(BaseModel):
    currency_code: str
    amount: float
    address: str

    @field_validator("amount")
    @classmethod
    def positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Сумма должна быть больше нуля")
        return v

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
    amount: float
    address: str
    status: str
    locked_until: datetime | None
    admin_note: str
    created_at: datetime
    processed_at: datetime | None


class WalletAdminWithdrawDecision(BaseModel):
    action: str  # "approve" | "reject" | "send"
    note: str = ""


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
    is_moderator: bool
    is_arbiter: bool
    is_vip: bool
    is_banned: bool
    is_frozen: bool
    balance: float
    deposit_total: float
    rating: float
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
    balance: float
    deposit_total: float
    rating_auto: float
    rating_manual: float | None
    rating_effective: float
    good: int
    bad: int
    deals_total: int
    deals_success: int
    deals_failed: int
    deals_arbitrage: int
    is_admin: bool
    is_moderator: bool
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

    Exactly one of the role flags may be true; pass all false to revoke
    privileges. ``is_moderator`` is intentionally unsupported per the
    spec — the field is still there in the DB but the admin panel does
    not grant it.
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
    deposit_total: float | None = None

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
    def _non_negative_float(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("Значение не может быть отрицательным")
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
    sum: float
    currency_code: str | None
    amount: float | None
    commission_amount: float | None
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
    """``user.balance`` + per-currency lock state at request time."""

    user_id: int
    username: str | None
    display_name: str
    currency_code: str | None
    amount: float
    locked: float
    total: float


class AdminDealEventItem(BaseModel):
    """One row in the deal's reconstructed event timeline.

    Built from the ``Deal`` row itself (no separate event table). Each
    timestamped column becomes its own item so the timeline UI can show
    a single ordered list without re-deriving anything.
    """

    at: datetime
    kind: str  # 'created' | 'in_progress' | 'cancel_request' | 'arbitration_started' | 'arbitration_resolved' | 'completed'
    actor: str | None  # 'buyer' | 'seller' | 'admin' | 'arbiter' | None
    description: str


class AdminDealDetailOut(BaseModel):
    """Full admin view of a deal."""

    id: int
    status: str
    description: str
    sum: float
    currency_code: str | None
    amount: float | None
    commission_amount: float | None
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

    buyer_percent: float
    reason: str | None = None

    @field_validator("buyer_percent")
    @classmethod
    def _percent_ok(cls, v: float) -> float:
        if v < 0 or v > 100:
            raise ValueError("Доля покупателя должна быть в диапазоне 0..100")
        return round(v, 2)


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
    price: float
    status: str
    ban_reason: str | None
    views: int
    deals_count: int
    deposit: float
    rating_manual: float | None
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
    price: float | None = None
    deposit: float | None = None
    views: int | None = None
    deals_count: int | None = None
    rating_manual: float | None = None
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
    def _non_negative_float(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("Значение не может быть отрицательным")
        return v

    @field_validator("views", "deals_count")
    @classmethod
    def _non_negative_int(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("Значение не может быть отрицательным")
        return v

    @field_validator("rating_manual")
    @classmethod
    def _rating_ok(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if v < 0 or v > 5:
            raise ValueError("Рейтинг должен быть в диапазоне 0..5")
        return round(v, 1)


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
