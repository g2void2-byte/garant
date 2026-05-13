"""Pydantic schemas for the FastAPI layer."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CategoryOut(BaseModel):
    id: int
    slug: str
    name: str
    icon_key: str
    services_count: int = 0


class ServiceOut(BaseModel):
    id: int
    owner_username: str
    title: str
    description: str
    price: float
    currency: str
    status: str
    category: CategoryOut
    created_at: str | None = None


class ServiceCreate(BaseModel):
    category_slug: str
    title: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    price: float = Field(..., ge=0)


class UserCard(BaseModel):
    id: int
    user_id: int
    username: str
    balance: float
    admin: int
    prefix: str | None
    good: int
    bad: int
    deposit: float
    rating: float
    reviews_count: int
    deals_count: int
    deals_sum: float
    online: bool
    banner_url: str | None
    description: str
    forums: list[dict] = []


class MeOut(UserCard):
    pass


class ProfileUpdate(BaseModel):
    description: str | None = None
    banner_url: str | None = None
    forums: list[dict] | None = None


class DealOut(BaseModel):
    id: int
    buyer: str
    seller: str
    sum: float
    description: str
    pay_comission: str
    status: str
    confirm_buyer: bool
    confirm_seller: bool
    role: Literal["buyer", "seller"]
    created_at: str | None


class DealCreate(BaseModel):
    counterparty: str = Field(..., min_length=1)
    role: Literal["buyer", "seller"]
    sum: float = Field(..., gt=0)
    description: str = Field(..., min_length=1, max_length=500)
    pay_comission: Literal["buyer", "seller"] = "buyer"


class ReviewOut(BaseModel):
    id: int
    deal_id: int | None
    author_username: str
    target_username: str
    rating: int
    text: str
    created_at: str


class ReviewCreate(BaseModel):
    target_username: str
    rating: int = Field(..., ge=1, le=5)
    text: str = Field(default="", max_length=1000)
    deal_id: int | None = None


class NotificationOut(BaseModel):
    id: int
    type: str
    title: str
    body: str
    payload: dict[str, Any] = {}
    is_read: bool
    created_at: str


class NotificationCounters(BaseModel):
    all: int = 0
    deals: int = 0
    deposits: int = 0
    system: int = 0
    unread: int = 0


class DepositOut(BaseModel):
    id: int
    amount: float
    status: str
    created_at: str
    released_at: str | None


class DepositCreate(BaseModel):
    amount: float = Field(..., gt=0)


class InvoiceOut(BaseModel):
    invoice_id: int | str
    pay_url: str
    amount: float
    asset: str


class InvoiceStatusOut(BaseModel):
    invoice_id: str
    status: str
    paid_amount: float = 0.0
    credited: bool = False


class WithdrawCreate(BaseModel):
    amount: float = Field(..., gt=0)


class SupportPerson(BaseModel):
    id: int
    user_id: int
    username: str
    admin: int
    prefix: str
