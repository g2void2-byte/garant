from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, field_validator

from .models import PayCommission

# ── Users ──────────────────────────────────────────────

class ForumOut(BaseModel):
    name: str
    url: str


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
    admin: int
    good: int
    bad: int
    rating: float
    reviews_count: int
    deals_count: int
    deals_sum: float
    online: bool
    forums: list[ForumOut]


class UserUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    banner_url: str | None = None
    forums: list[ForumOut] | None = None


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


# ── Deals ──────────────────────────────────────────────

class DealCreate(BaseModel):
    counterparty: str
    role: str
    sum: float
    description: str = ""
    pay_comission: PayCommission = PayCommission.buyer


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


# ── Reviews ────────────────────────────────────────────

class ReviewCreate(BaseModel):
    target_username: str
    rating: int
    text: str = ""
    deal_id: int | None = None


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


class WithdrawReq(BaseModel):
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
    admin: int
    prefix: str
