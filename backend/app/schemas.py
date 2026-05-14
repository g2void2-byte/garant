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
    amount: float
    locked: float
    total: float
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
    total_usd_estimate: float


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
    amount: float
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
    def _amount_ok(cls, v: float) -> float:
        if v == 0:
            raise ValueError("Сумма не может быть равна нулю")
        return v

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
    amount: float
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
    amount: float
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
    accrued: float
    withdrawn: float
    available: float


class AdminTreasuryOverviewOut(BaseModel):
    balances: list[AdminTreasuryBalanceOut]
    total_withdrawals: int


class AdminTreasuryWithdrawIn(BaseModel):
    """Body for ``POST /api/admin/treasury/withdraw``.

    Requires the ``X-Totp-Code`` header (validated by a dependency) and
    ``confirm=true`` to satisfy the double-confirm gate.
    """

    currency_code: str
    amount: float
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
    def _amount_ok(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Сумма должна быть положительной")
        return v

    @field_validator("address")
    @classmethod
    def _address_ok(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Адрес не может быть пустым")
        if len(v) > 256:
            raise ValueError("Адрес слишком длинный (≤256)")
        return v


class AdminTreasuryWithdrawOut(BaseModel):
    id: int
    actor_id: int
    currency_code: str
    amount: float
    address: str
    status: str
    note: str
    cryptobot_transfer_id: str | None
    created_at: datetime


# ── Admin: settings (PR-CDE) ───────────────────────────


class AdminSettingsOut(BaseModel):
    deal_commission_percent: float
    invoice_commission_percent: float
    vip_commission_percent: float
    min_deposit: float
    min_withdraw: float
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

    deal_commission_percent: float | None = None
    invoice_commission_percent: float | None = None
    vip_commission_percent: float | None = None
    min_deposit: float | None = None
    min_withdraw: float | None = None
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
    def _commission_ok(cls, v: float | None) -> float | None:
        if v is None:
            return v
        # ``vip_commission_percent`` allows -1 ("no override").
        if v < -1 or v > 100:
            raise ValueError("Комиссия должна быть в диапазоне -1..100")
        return round(v, 2)

    @field_validator(
        "min_deposit",
        "min_withdraw",
    )
    @classmethod
    def _min_ok(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if v < 0:
            raise ValueError("Значение не может быть отрицательным")
        return v

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
    min_deposit: float
    min_withdraw: float
    is_active: bool
    sort_order: int


class AdminCurrencyUpsertIn(BaseModel):
    code: str
    name: str | None = None
    network: str | None = None
    icon_url: str | None = None
    decimals: int | None = None
    min_deposit: float | None = None
    min_withdraw: float | None = None
    is_active: bool | None = None
    sort_order: int | None = None

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
    def _min_ok(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if v < 0:
            raise ValueError("Значение не может быть отрицательным")
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
        return v

    @field_validator("audience_active_days", "audience_min_deals")
    @classmethod
    def _int_ok(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 0:
            raise ValueError("Значение не может быть отрицательным")
        return v


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
    value: float


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


# ── Admin: audit log (PR-CDE) ──────────────────────────


class AdminAuditLogListOut(BaseModel):
    items: list[AdminAuditLogOut]
    total: int
    page: int
    page_size: int
