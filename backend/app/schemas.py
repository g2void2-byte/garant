from __future__ import annotations

import json
from datetime import datetime

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
