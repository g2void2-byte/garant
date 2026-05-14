from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class DealStatus(str, enum.Enum):
    """Deal lifecycle. Values match the Continental reference bundle
    (`pending_confirmation`, `in_progress`, `arbitration`, ...).

    Terminal states: ``cancelled``, ``completed``, ``resolved_for_buyer``,
    ``resolved_for_seller``, ``cancelled_for_inactivity``.
    """

    cancelled = "cancelled"  # 0
    pending_confirmation = "pending_confirmation"  # 1
    pending_payment = "pending_payment"  # 2 (reserved; not used today)
    in_progress = "in_progress"  # 3
    completed = "completed"  # 4
    arbitration = "arbitration"  # 5
    resolved_for_buyer = "resolved_for_buyer"  # 6
    resolved_for_seller = "resolved_for_seller"  # 7
    pending_cancellation = "pending_cancellation"  # 8
    cancelled_for_inactivity = "cancelled_for_inactivity"  # 9


TERMINAL_DEAL_STATUSES = frozenset(
    {
        DealStatus.cancelled,
        DealStatus.completed,
        DealStatus.resolved_for_buyer,
        DealStatus.resolved_for_seller,
        DealStatus.cancelled_for_inactivity,
    }
)


class PayCommission(str, enum.Enum):
    buyer = "buyer"
    seller = "seller"


class NotificationType(str, enum.Enum):
    deals = "deals"
    deposits = "deposits"
    system = "system"


class InvoiceStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    expired = "expired"


class InvoiceProvider(str, enum.Enum):
    cryptobot = "cryptobot"


class WalletDepositStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    expired = "expired"


class WalletWithdrawStatus(str, enum.Enum):
    pending = "pending"  # awaiting admin review
    approved = "approved"  # admin OK, funds locked, waiting for the timer
    sent = "sent"  # paid out
    rejected = "rejected"  # declined, funds returned


class ServiceStatus(str, enum.Enum):
    """Service moderation lifecycle.

    * ``draft``    — the owner is still editing; hidden from public.
    * ``active``   — visible in catalog and search.
    * ``paused``   — owner-side hide (keeps the row, hides from catalog).
    * ``banned``   — admin-side ban (hidden, owner cannot reactivate).
    """

    draft = "draft"
    active = "active"
    paused = "paused"
    banned = "banned"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    banner_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    balance: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    frozen_balance: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    description: Mapped[str] = mapped_column(Text, default="")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_arbiter: Mapped[bool] = mapped_column(Boolean, default=False)
    deals_total: Mapped[int] = mapped_column(Integer, default=0)
    deals_success: Mapped[int] = mapped_column(Integer, default=0)
    deals_failed: Mapped[int] = mapped_column(Integer, default=0)
    deals_arbitrage: Mapped[int] = mapped_column(Integer, default=0)
    good: Mapped[int] = mapped_column(Integer, default=0)
    bad: Mapped[int] = mapped_column(Integer, default=0)
    pin_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pin_attempts: Mapped[int] = mapped_column(Integer, default=0)
    pin_locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pin_reset_code_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pin_reset_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # PR-G — DM notification preferences (one toggle per NotificationType bucket).
    dm_deals: Mapped[bool] = mapped_column(Boolean, default=True)
    dm_deposits: Mapped[bool] = mapped_column(Boolean, default=True)
    dm_system: Mapped[bool] = mapped_column(Boolean, default=True)
    # P3.2 — privacy toggles surfaced in the bot "Настройки" submenu.
    is_anonymous_deals: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hidden_profile: Mapped[bool] = mapped_column(Boolean, default=False)
    # Admin PR-A — moderation state. ``is_banned`` blocks deal/service
    # creation and withdrawals; ``is_frozen`` blocks spending only.
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    ban_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    freeze_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Admin PR-A — VIP prefix, manually granted by admins. Shown next to
    # the username and (in a later PR) entitles the user to a reduced
    # commission rate configured in the global settings.
    is_vip: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Admin PR-A — passive connection fingerprint, refreshed by
    # ``get_current_user`` on every authenticated request.
    last_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    login_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Admin PR-A — aggregate stats editable by an admin via /admin/users/:id/stats
    deposit_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    # Admin PR-A — optional override of the *computed* rating (see
    # services.py:_recompute_user_rating). When non-null this value
    # takes precedence in profile responses; setting to null restores
    # the auto-computed rating.
    rating_manual: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    # Admin PR-CDE — TOTP secret used to gate treasury withdrawals and
    # user deletion. ``totp_enabled`` is set the moment the user has
    # confirmed a code; resetting drops both fields back to NULL.
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # P3.4 — full-text search vector. Computed by Postgres on INSERT/UPDATE.
    # Weight A = username (more important), Weight B = display_name + description.
    # NB: ``simple`` config is intentional — we serve a Russian/English mixed
    # audience and don't want stemming on usernames.
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple', coalesce(username, '')), 'A') || "
            "setweight(to_tsvector('simple', coalesce(display_name, '')), 'B') || "
            "setweight(to_tsvector('simple', coalesce(description, '')), 'C')",
            persisted=True,
        ),
        nullable=True,
    )

    services: Mapped[list[Service]] = relationship(back_populates="owner", lazy="selectin")
    forums: Mapped[list[Forum]] = relationship(back_populates="owner", lazy="selectin")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    icon: Mapped[str] = mapped_column(String(64), default="")

    services: Mapped[list[Service]] = relationship(back_populates="category", lazy="selectin")


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    status: Mapped[ServiceStatus] = mapped_column(
        Enum(ServiceStatus), default=ServiceStatus.active, index=True
    )
    ban_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Admin PR-A — service stats editable by an admin via
    # /admin/services/:id/stats. These are *display* fields used on the
    # service detail page; they do not influence the deal state machine.
    views: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    deals_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    deposit: Mapped[float] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    rating_manual: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # P3.4 — full-text search vector. Title is weighted higher than description.
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('simple', coalesce(description, '')), 'B')",
            persisted=True,
        ),
        nullable=True,
    )

    owner: Mapped[User] = relationship(back_populates="services", lazy="selectin")
    category: Mapped[Category] = relationship(back_populates="services", lazy="selectin")


class ServiceComment(Base):
    """A short comment / mini-review left on a specific :class:`Service`.

    Comments are public (visible to anyone who can see the service) and
    can be deleted by their author, the service owner, or an admin.
    A 1-5 ``rating`` is optional — Continental shows comments with and
    without a star rating side-by-side.
    """

    __tablename__ = "service_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    service: Mapped[Service] = relationship(foreign_keys=[service_id], lazy="selectin")
    author: Mapped[User] = relationship(foreign_keys=[author_id], lazy="selectin")


class Deal(Base):
    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    sum: Mapped[float] = mapped_column(Numeric(14, 2))
    description: Mapped[str] = mapped_column(Text, default="")
    pay_commission: Mapped[PayCommission] = mapped_column(
        Enum(PayCommission), default=PayCommission.buyer
    )
    status: Mapped[DealStatus] = mapped_column(
        Enum(DealStatus), default=DealStatus.pending_confirmation, index=True
    )
    confirm_buyer: Mapped[bool] = mapped_column(Boolean, default=False)
    confirm_seller: Mapped[bool] = mapped_column(Boolean, default=False)
    arbitrage_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Multi-currency fields (PR-3). ``currency_id`` is nullable for legacy
    # rows that lived on the old ``User.balance`` USD column. New deals
    # always set it.
    currency_id: Mapped[int | None] = mapped_column(
        ForeignKey("currencies.id"), nullable=True, index=True
    )
    amount: Mapped[float | None] = mapped_column(Numeric(28, 8), nullable=True)
    commission_amount: Mapped[float | None] = mapped_column(Numeric(28, 8), nullable=True)
    in_progress_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Cancel-debate flow.
    cancellation_initiator_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Arbitration flow.
    arbitration_initiator_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    arbitration_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    arbitration_resolved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    arbitration_resolution: Mapped[str | None] = mapped_column(String(16), nullable=True)
    arbitration_resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    buyer: Mapped[User] = relationship(foreign_keys=[buyer_id], lazy="selectin")
    seller: Mapped[User] = relationship(foreign_keys=[seller_id], lazy="selectin")
    currency: Mapped[Currency | None] = relationship(foreign_keys=[currency_id], lazy="selectin")


class DealMessage(Base):
    """An in-app chat message attached to a deal.

    Restricted to deal participants (buyer + seller) and admins/arbiters.
    ``attachments_json`` stores a JSON-encoded list of ``Media.id`` values
    uploaded via ``/api/media/upload`` with ``kind="deal"`` — keeping the
    media table as the single source of truth for files.
    """

    __tablename__ = "deal_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    attachments_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    sender: Mapped[User] = relationship(foreign_keys=[sender_id], lazy="selectin")


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id"), nullable=True)
    rating: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    author: Mapped[User] = relationship(foreign_keys=[author_id], lazy="selectin")
    target: Mapped[User] = relationship(foreign_keys=[target_id], lazy="selectin")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType), default=NotificationType.system
    )
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    recipient: Mapped[User] = relationship(foreign_keys=[recipient_id], lazy="selectin")


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    provider: Mapped[InvoiceProvider] = mapped_column(
        Enum(InvoiceProvider), default=InvoiceProvider.cryptobot
    )
    provider_invoice_id: Mapped[str] = mapped_column(String(256), unique=True)
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus), default=InvoiceStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    owner: Mapped[User] = relationship(foreign_keys=[owner_id], lazy="selectin")


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_commission_percent: Mapped[float] = mapped_column(Numeric(5, 2), default=5.0)
    invoice_commission_percent: Mapped[float] = mapped_column(Numeric(5, 2), default=0.0)
    min_deposit: Mapped[float] = mapped_column(Numeric(14, 2), default=1.0)
    min_withdraw: Mapped[float] = mapped_column(Numeric(14, 2), default=1.0)
    # PR-3 — auto-cancel timeouts.
    inactivity_pending_confirmation_days: Mapped[int] = mapped_column(Integer, default=7)
    inactivity_pending_cancellation_days: Mapped[int] = mapped_column(Integer, default=3)
    # PR-6 — maximum simultaneously-active services per user.
    max_active_services_per_user: Mapped[int] = mapped_column(Integer, default=10)
    # Admin PR-CDE — VIP commission override. When >=0 it replaces
    # ``deal_commission_percent`` for users with ``is_vip=true``;
    # ``-1`` means "no override, charge the normal rate".
    vip_commission_percent: Mapped[float] = mapped_column(
        Numeric(5, 2), default=-1.0, server_default="-1"
    )
    # Admin PR-CDE — global maintenance switch. When ``True`` the bot
    # and TMA both display a maintenance banner and reject every write
    # except for callers with ``is_admin=true``.
    maintenance_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    maintenance_message: Mapped[str] = mapped_column(
        Text,
        default="Сервис на технических работах. Зайдите позже.",
        server_default="Сервис на технических работах. Зайдите позже.",
    )
    # Admin PR-CDE — when ``True`` approved withdrawals are pushed to
    # CryptoBot Transfer immediately; otherwise they stay in the
    # ``approved`` queue waiting for a manual ``mark sent``.
    auto_withdraw_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )


class Forum(Base):
    __tablename__ = "forums"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(256), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    owner: Mapped[User] = relationship(back_populates="forums", lazy="selectin")


class Media(Base):
    """Uploaded image / file.

    Stored on disk under ``settings.media_root`` and served via
    ``settings.media_base_url``.  ``kind`` is a free-form bucket name
    ("avatar", "banner", "deal", ...) used to group uploads and apply
    per-bucket policy.
    """

    __tablename__ = "media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    url: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(256), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    content_type: Mapped[str] = mapped_column(String(64), default="application/octet-stream")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ── Multi-currency wallet ──────────────────────────────


class Currency(Base):
    """A supported asset.

    The wallet is a thin UI layer over CryptoBot: ``code`` matches the
    CryptoBot asset identifier and ``decimals`` controls how amounts are
    rendered in the client.
    """

    __tablename__ = "currencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    network: Mapped[str] = mapped_column(String(32), default="")
    icon_url: Mapped[str] = mapped_column(Text, default="")
    decimals: Mapped[int] = mapped_column(Integer, default=2)
    min_deposit: Mapped[float] = mapped_column(Numeric(18, 8), default=1)
    min_withdraw: Mapped[float] = mapped_column(Numeric(18, 8), default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class UserBalance(Base):
    """A user's balance in a specific currency.

    Funds are split into ``amount`` (spendable) and ``locked`` (held
    while a withdrawal is pending or during the 72h cool-down).
    """

    __tablename__ = "user_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    currency_id: Mapped[int] = mapped_column(ForeignKey("currencies.id"), index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 8), default=0)
    locked: Mapped[float] = mapped_column(Numeric(18, 8), default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="selectin")
    currency: Mapped[Currency] = relationship(foreign_keys=[currency_id], lazy="selectin")


class WalletDeposit(Base):
    """A CryptoBot invoice issued for a wallet top-up."""

    __tablename__ = "wallet_deposits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    currency_id: Mapped[int] = mapped_column(ForeignKey("currencies.id"), index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 8))
    provider: Mapped[InvoiceProvider] = mapped_column(
        Enum(InvoiceProvider), default=InvoiceProvider.cryptobot
    )
    provider_invoice_id: Mapped[str] = mapped_column(String(256), index=True)
    pay_url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[WalletDepositStatus] = mapped_column(
        Enum(WalletDepositStatus), default=WalletDepositStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="selectin")
    currency: Mapped[Currency] = relationship(foreign_keys=[currency_id], lazy="selectin")


class WalletWithdrawal(Base):
    """A withdrawal request manually processed by an admin.

    Funds move from ``UserBalance.amount`` to ``UserBalance.locked`` on
    creation. On approval the admin sends the payout and marks the row
    ``sent``; on rejection the funds are returned to ``amount``.
    """

    __tablename__ = "wallet_withdrawals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    currency_id: Mapped[int] = mapped_column(ForeignKey("currencies.id"), index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 8))
    address: Mapped[str] = mapped_column(String(256))
    status: Mapped[WalletWithdrawStatus] = mapped_column(
        Enum(WalletWithdrawStatus), default=WalletWithdrawStatus.pending
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="selectin")
    currency: Mapped[Currency] = relationship(foreign_keys=[currency_id], lazy="selectin")


# ── Account transfer (PR-CA) ───────────────────────────


class AccountTransferCode(Base):
    """One-time code that re-points a user's ``tg_user_id`` to a new
    Telegram account.

    Issued by the existing (source) account from a PIN-gated endpoint and
    delivered via the bot DM. Consumed by the new (target) account once
    they enter the code on the new device.
    """

    __tablename__ = "account_transfer_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    target_tg_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    source_user: Mapped[User] = relationship(foreign_keys=[source_user_id], lazy="selectin")


class TreasuryWithdrawal(Base):
    """Admin-initiated withdrawal of accumulated commission.

    Tracks payouts of the platform's commission balance to an external
    address. Requires 2FA + double-confirm on creation; status moves
    ``pending`` → ``sent`` (or ``rejected``) once the CryptoBot transfer
    completes. Currency is stored by ``currency_id`` so the
    ``treasury_balance`` view can aggregate by asset.
    """

    __tablename__ = "treasury_withdrawals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    currency_id: Mapped[int] = mapped_column(ForeignKey("currencies.id"), index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 8))
    address: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(
        String(16), default="sent", server_default="sent", index=True
    )
    note: Mapped[str] = mapped_column(Text, default="")
    cryptobot_transfer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    actor: Mapped[User] = relationship(foreign_keys=[actor_id], lazy="selectin")
    currency: Mapped[Currency] = relationship(foreign_keys=[currency_id], lazy="selectin")


class Broadcast(Base):
    """Admin-authored push delivered in-app and/or via Telegram DM.

    Stores the *intent* (audience filter + body + dispatch flags); the
    actual recipients are computed at send time and counted into
    ``total_recipients`` / ``delivered_count``.  ``status`` is ``draft``
    when scheduled (``scheduled_at`` set), ``sent`` once dispatched.
    """

    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    body: Mapped[str] = mapped_column(Text)
    deeplink: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Audience filters — all optional; empty = "everyone".
    audience_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    audience_active_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audience_min_deals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Dispatch flags.
    dispatch_inapp: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    dispatch_dm: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Lifecycle.
    status: Mapped[str] = mapped_column(
        String(16), default="sent", server_default="sent", index=True
    )
    total_recipients: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    delivered_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    actor: Mapped[User] = relationship(foreign_keys=[actor_id], lazy="selectin")


class AdminAuditLog(Base):
    """Append-only log of admin actions.

    A row is written for every privileged operation performed via the
    :file:`backend/app/routers/admin/*` endpoints. Designed for forensics
    and the ``/admin/audit`` viewer — never modified or deleted from
    production code.
    """

    __tablename__ = "admin_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    actor: Mapped[User | None] = relationship(foreign_keys=[actor_id], lazy="selectin")
