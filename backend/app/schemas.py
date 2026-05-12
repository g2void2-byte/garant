"""Pydantic schemas for API I/O."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import DealStatus, TxType


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tg_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    photo_url: str | None
    balance: float
    frozen: float
    insurance: float
    rating: float
    deals_total: int
    deals_success: int
    is_admin: bool
    is_banned: bool
    created_at: datetime


class UserShort(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tg_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    photo_url: str | None
    rating: float


class DealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    amount: float
    commission: float
    status: DealStatus
    buyer: UserShort
    seller: UserShort
    creator_id: int
    created_at: datetime
    funded_at: datetime | None
    completed_at: datetime | None
    dispute_reason: str | None


class DealCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = ""
    amount: float = Field(gt=0)
    # Counterparty by tg_id or username (without @)
    counterparty_tg_id: int | None = None
    counterparty_username: str | None = None
    role: Literal["buyer", "seller"]


class DealAction(BaseModel):
    action: Literal[
        "fund",
        "confirm",
        "cancel",
        "open_dispute",
        "release",
        "refund",
    ]
    reason: str | None = None


class BalanceOp(BaseModel):
    amount: float = Field(gt=0)
    note: str | None = None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: TxType
    amount: float
    deal_id: int | None
    note: str | None
    created_at: datetime


class SettingsOut(BaseModel):
    commission_percent: float
    insurance_deposit: float
    welcome_message: str


class SettingsUpdate(BaseModel):
    commission_percent: float | None = Field(default=None, ge=0, le=100)
    insurance_deposit: float | None = Field(default=None, ge=0)
    welcome_message: str | None = None


class AdminUserUpdate(BaseModel):
    balance_delta: float | None = None
    insurance_delta: float | None = None
    is_banned: bool | None = None
    is_admin: bool | None = None
    rating: float | None = Field(default=None, ge=0, le=5)
    note: str | None = None


class StatsOut(BaseModel):
    users_total: int
    users_active_7d: int
    deals_total: int
    deals_in_escrow: int
    volume_total: float
    commission_total: float
