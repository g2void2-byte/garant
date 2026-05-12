"""ORM models for AutoGarant."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class DealStatus(enum.StrEnum):
    """Lifecycle states for a deal."""

    DRAFT = "draft"
    AWAITING_PAYMENT = "awaiting_payment"
    FUNDED = "funded"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    DISPUTED = "disputed"
    REFUNDED = "refunded"


class TxType(enum.StrEnum):
    """Balance transaction types."""

    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"
    HOLD = "hold"
    RELEASE = "release"
    REFUND = "refund"
    COMMISSION = "commission"
    INSURANCE_LOCK = "insurance_lock"
    INSURANCE_UNLOCK = "insurance_unlock"
    ADMIN_ADJUST = "admin_adjust"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), index=True)
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    photo_url: Mapped[str | None] = mapped_column(String(512))

    balance: Mapped[float] = mapped_column(Float, default=0.0)
    frozen: Mapped[float] = mapped_column(Float, default=0.0)
    insurance: Mapped[float] = mapped_column(Float, default=0.0)
    rating: Mapped[float] = mapped_column(Float, default=5.0)
    deals_total: Mapped[int] = mapped_column(Integer, default=0)
    deals_success: Mapped[int] = mapped_column(Integer, default=0)

    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Deal(Base):
    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    amount: Mapped[float] = mapped_column(Float)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[DealStatus] = mapped_column(
        Enum(DealStatus), default=DealStatus.AWAITING_PAYMENT
    )

    buyer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    buyer: Mapped[User] = relationship("User", foreign_keys=[buyer_id], lazy="joined")
    seller: Mapped[User] = relationship("User", foreign_keys=[seller_id], lazy="joined")
    creator: Mapped[User] = relationship("User", foreign_keys=[creator_id], lazy="joined")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    funded_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    dispute_reason: Mapped[str | None] = mapped_column(Text)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[TxType] = mapped_column(Enum(TxType))
    amount: Mapped[float] = mapped_column(Float)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id"))
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Setting(Base):
    """Key-value settings overridable via admin UI."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
