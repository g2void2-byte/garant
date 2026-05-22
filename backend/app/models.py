from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    text as sa_text,
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
    # Audit M3 — DEPRECATED. The value is preserved in the Postgres
    # ENUM because there is no ``ALTER TYPE ... DROP VALUE`` in
    # Postgres and rebuilding ``dealstatus`` via a shadow type would
    # be disproportionate. No transition currently writes this status;
    # admin filters / dashboard counters that used to include it have
    # been dropped. Do NOT add new code that transitions deals into
    # this state — the buyer/seller flows assume only the statuses
    # below.
    pending_payment = "pending_payment"  # 2 (DEPRECATED, see note)
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


# H-1 — ``InvoiceStatus`` and ``InvoiceProvider`` were the legacy USD
# ``invoices``-table enums. The ``Invoice`` model + status enum were
# deleted alongside ``User.balance``; the DB enum type
# ``invoiceprovider`` was renamed to ``walletdepositprovider`` by the
# H-1 migration so the surviving ``WalletDeposit.provider`` column
# keeps a stable Python enum type without a destructive re-create.
# New code should reference :class:`WalletDepositProvider` only.
class WalletDepositProvider(str, enum.Enum):
    """Payment provider that backed a ``WalletDeposit`` row.

    L-6 trade-off — *kept as a Postgres ``ENUM`` rather than a free-form
    string column*.

    The single-valued enum (only ``cryptobot`` is supported today) reads
    like over-engineering at first glance: a ``String(32)`` plus a
    ``CheckConstraint`` would store the same data and avoid the
    ``ALTER TYPE ... ADD VALUE`` dance every new provider triggers.
    We keep the ENUM anyway because:

    * **Type safety at the ORM boundary.** SA materialises rows into
      :class:`WalletDepositProvider` members, so a typo (``"cryptobot
      "`` with a trailing space, mis-cased ``"CryptoBot"``) is rejected
      at write time instead of silently flowing into the wallet ledger
      and the admin "deposits by provider" analytics.
    * **PR-G enum-renaming precedent.** H-1 already proved we can rename
      a Postgres enum (``invoiceprovider`` → ``walletdepositprovider``)
      in-place without a destructive re-create. Adding a new provider
      is a one-line :func:`op.execute("ALTER TYPE walletdepositprovider
      ADD VALUE 'foo'")` migration — fast, in-transaction, and a single
      transactional commit. The cost we are deferring is *removing*
      a provider, which would need a downgrade-style V5-E-1 dance —
      see :data:`tests.test_v5_d_e_bucket._DESTRUCTIVE_DOWNGRADES`.

    The alternative — ``String(32)`` + ``CheckConstraint("provider IN
    ('cryptobot', …)")`` — looks lighter but loses the typed ORM
    surface, leaks the validation list across migration files (the
    CHECK has to be ALTER'd on every change, same lock cost as ADD
    VALUE), and gives nothing in return for an enum that has had
    exactly one value through three audit cycles.

    Mig-3 hardening: a future provider addition should land as its
    own migration with the ``ADD VALUE`` call inside a regular
    transactional block (``ADD VALUE`` is one of the few ``ALTER
    TYPE`` operations Postgres allows inside a transaction); the
    matching downgrade is a no-op and gets a V5-E-1 marker because
    ``ALTER TYPE ... DROP VALUE`` doesn't exist in Postgres.
    ``crystalpay`` was added via the
    ``q7d8e2c1f4a9_add_crystalpay_provider_value`` migration.
    """

    cryptobot = "cryptobot"
    crystalpay = "crystalpay"


class WalletDepositStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    expired = "expired"
    # PR-H (M-16) — admin-initiated reversal of a credited deposit.
    # ``expired`` is reserved for CryptoBot-side expiry of an
    # unpaid invoice; a refund is a distinct state and is what the
    # admin badge / analytics filter want to see.
    refunded = "refunded"


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
    __table_args__ = (
        # Mirrors the ``ck_users_country_iso_alpha2`` CHECK constraint
        # added in migration ``t2b3c4d5e6f7`` — see that revision for
        # the rationale. ``country`` is either ``NULL`` or an uppercase
        # ISO-3166-1 alpha-2 code.
        CheckConstraint(
            "country IS NULL OR country ~ '^[A-Z]{2}$'",
            name="ck_users_country_iso_alpha2",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    banner_url: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # Session epoch — every PIN token embeds this value; admin
    # ``invalidate-sessions`` bumps it so existing tokens stop
    # decoding to a valid (user, epoch) pair before their TTL.
    pin_session_epoch: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Reset-request throttle (per-user, 3 codes per 24h). The window
    # opens on the first request after a quiet period and closes after
    # 24h, at which point the counter resets.
    pin_reset_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    pin_reset_window_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # PR-G — DM notification preferences (one toggle per NotificationType bucket).
    dm_deals: Mapped[bool] = mapped_column(Boolean, default=True)
    dm_deposits: Mapped[bool] = mapped_column(Boolean, default=True)
    dm_system: Mapped[bool] = mapped_column(Boolean, default=True)
    # P3.2 — privacy toggles surfaced in the bot "Настройки" submenu.
    is_anonymous_deals: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hidden_profile: Mapped[bool] = mapped_column(Boolean, default=False)
    # Admin PR-A — moderation state. Both flags hard-block the user
    # at the ``deps.current_user`` gate: every request to ``/api/*``
    # returns 403 with the corresponding admin reason. ``is_banned``
    # is the permanent/severe state; ``is_frozen`` is the lighter
    # admin tool with its own freeze_reason. The Russian-language
    # difference is purely UX wording (banned = "заблокирован",
    # frozen = "заморожен") so admins can communicate severity to
    # the user; the enforcement is identical.
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
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    # A-6 — IETF language tag the Telegram client sent on first / last
    # auth (``user.language_code`` in the initData blob, e.g. ``"ru"``,
    # ``"en"``, ``"pt-br"``). Refreshed by ``get_current_user`` on the
    # same debounce schedule as ``last_login_at`` so a user switching
    # phone locale propagates to admin broadcasts within ~5 min. The
    # column is indexed because the admin broadcast composer filters on
    # exact-match values (Telegram normalises to lowercase ISO codes,
    # so cardinality stays bounded; no need for FTS / trigram).
    language_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    # "Sessions seen by the API" — bumped on the first authenticated
    # request after a quiet window of ``deps._LAST_LOGIN_DEBOUNCE``
    # (5 min). NOT a literal Telegram login event nor a per-request
    # counter: a user pulling-to-refresh five times in a minute still
    # adds 1, a user coming back the next day adds 1 more. The admin
    # panel still surfaces this as "Логинов" because that label maps
    # cleanly onto the debounced semantics; if the debounce window
    # ever changes, update both the column comment and the admin
    # copy.
    login_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Admin PR-A — aggregate stats editable by an admin via /admin/users/:id/stats.
    # H-2 widened from ``Numeric(14, 2)`` to ``Numeric(28, 8)`` so the
    # lifetime deposit aggregate matches the per-currency ledger
    # precision and a satoshi-scale top-up no longer truncates on
    # write. The migration backfills nothing because every existing
    # value already fits inside the wider shape.
    deposit_total: Mapped[float] = mapped_column(Numeric(28, 8), default=0, server_default="0")
    # Trust deposit — money the user voluntarily locks into the bot as a
    # trust signal. ``services_wallet.credit_deposit`` routes deposits
    # created with ``purpose="trust"`` here instead of ``UserBalance``;
    # there is *no* withdraw / spend path for this balance (lock-in by
    # design). Surfaced publicly as the ``deposit`` field on ``UserOut``
    # / ``UserPublicOut`` so other users can see how much trust capital
    # a counterparty has put up. Distinct from ``deposit_total`` which
    # is the admin-editable lifetime aggregate.
    trust_deposit_balance: Mapped[float] = mapped_column(
        Numeric(28, 8), default=0, server_default="0"
    )
    # ISO-3166-1 alpha-2 country code chosen by the user in profile
    # settings. ``None`` means "not set". Surfaced on every public
    # profile (``UserCard`` / ``ProfileHeader``); the flag emoji + name
    # are computed client-side from a static list in
    # ``frontend/src/lib/countries.ts``.
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
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
    # Review pass 3 — RFC 6238 §5.2 replay protection. Stores the
    # ``int(time.time()) // 30`` counter of the most recently accepted
    # code; any code at or below this counter is rejected so a leaked
    # 6-digit code can't be reused inside its 30-second window.
    # ``-1`` means "no code accepted yet".
    totp_last_counter: Mapped[int] = mapped_column(BigInteger, default=-1, server_default="-1")
    # TOTP-session epoch — every minted ``X-Totp-Session`` JWT embeds
    # this value; bumping it (via ``2fa.disable`` / rotation /
    # ``invalidate-sessions``) revokes every outstanding 24h session
    # immediately, without waiting for the JWT TTL.
    totp_session_epoch: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Rolling "last authenticated request" timestamp. Updated by
    # ``get_current_user`` (debounced via
    # ``settings.pin_activity_debounce_seconds``) whenever a request
    # carries a valid PIN session token, and consumed by
    # ``require_pin_session`` to enforce the 30-min idle window. NULL
    # for accounts that have never unlocked a PIN session — those are
    # treated as "no activity" and fall through to JWT TTL.
    pin_last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
    __table_args__ = (
        # Mirrors the ``ck_services_photo_urls_max_6`` CHECK constraint
        # added in migration ``t2b3c4d5e6f7`` — see that revision for
        # the rationale. The cap of 6 matches the application-layer
        # ``MAX_SERVICE_PHOTOS`` in ``backend/app/schemas.py``.
        CheckConstraint(
            "jsonb_typeof(photo_urls) = 'array' AND jsonb_array_length(photo_urls) <= 6",
            name="ck_services_photo_urls_max_6",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # M-13: CASCADE so deleting the owner also deletes their services.
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    # H-2 — widened from ``Numeric(14, 2)`` to ``Numeric(28, 8)`` so a
    # service priced in a satoshi-scale crypto (USDT @ 8 decimals,
    # BTC @ 8 decimals) round-trips without truncation. ``Service.price``
    # is a per-currency catalogue figure; the deal that materialises
    # from the service copies it into ``Deal.amount`` which already
    # uses ``Numeric(28, 8)``.
    price: Mapped[float] = mapped_column(Numeric(28, 8), default=0)
    status: Mapped[ServiceStatus] = mapped_column(
        Enum(ServiceStatus), default=ServiceStatus.active, index=True
    )
    ban_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Admin PR-A — service stats editable by an admin via
    # /admin/services/:id/stats. These are *display* fields used on the
    # service detail page; they do not influence the deal state machine.
    views: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    deals_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # H-2 — widened from ``Numeric(14, 2)`` to ``Numeric(28, 8)`` for
    # the same reason as ``Service.price``: the deposit threshold is a
    # per-currency money figure that must survive 8-decimal asset
    # round-trips intact.
    #
    # Audit §5.7 / §6.3 — this column is currently *admin-curated
    # catalog metadata* (editable from ``admin/content`` + rendered on
    # the service detail card), not a runtime gate for the deal flow
    # itself. The deal pipeline keys off ``Deal.amount`` /
    # ``Deal.currency_id`` and per-user ``UserBalance`` rows; nothing
    # in ``services_deals.py`` or ``services_wallet.py`` reads this
    # field today. Kept on the model rather than dropped via a
    # destructive migration so service rows that already store a value
    # don't have to be backfilled, and so a future "minimum-deposit
    # to-open-a-deal" gate can be enabled by referencing this column
    # without a new migration. If you decide to repurpose it, document
    # the new semantics here and remove this paragraph.
    deposit: Mapped[float] = mapped_column(Numeric(28, 8), default=0, server_default="0")
    rating_manual: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    # V12-UI — gallery of attachments uploaded for the service. Stored as
    # a JSON list of strings (each is either an ``https://...`` external
    # URL or a ``/media/...`` path produced by ``POST /api/media/upload``
    # with ``kind=service``). Capped at ``MAX_SERVICE_PHOTOS`` (6) by the
    # ``ServiceCreate``/``ServiceUpdate`` validators so the catalogue
    # endpoint stays cheap to render. ``server_default`` is a JSON
    # empty-list literal so existing rows hydrate as ``[]`` and the
    # column never returns ``None`` to the application layer.
    photo_urls: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=sa_text("'[]'::jsonb"),
    )
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

    # M-2: optional FK to ``currencies``. Nullable so existing rows
    # (created before multi-currency support) default to NULL (= USD).
    currency_id: Mapped[int | None] = mapped_column(
        ForeignKey("currencies.id"), nullable=True, index=True
    )

    owner: Mapped[User] = relationship(back_populates="services", lazy="selectin")
    category: Mapped[Category] = relationship(back_populates="services", lazy="selectin")
    currency: Mapped[Currency | None] = relationship(lazy="selectin")


class ServiceComment(Base):
    """A short comment / mini-review left on a specific :class:`Service`.

    Comments are public (visible to anyone who can see the service) and
    can be deleted by their author, the service owner, or an admin.
    A 1-5 ``rating`` is optional — Continental shows comments with and
    without a star rating side-by-side.
    """

    __tablename__ = "service_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_id: Mapped[int] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
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
    description: Mapped[str] = mapped_column(Text, default="")
    pay_commission: Mapped[PayCommission] = mapped_column(
        Enum(PayCommission), default=PayCommission.buyer
    )
    status: Mapped[DealStatus] = mapped_column(
        Enum(DealStatus), default=DealStatus.pending_confirmation, index=True
    )
    confirm_buyer: Mapped[bool] = mapped_column(Boolean, default=False)
    confirm_seller: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    # Multi-currency fields (PR-3). After L-2 the legacy USD-only
    # ``Deal.sum`` (Numeric(14,2)) column is gone; ``amount`` /
    # ``currency_id`` are NOT NULL on every row because the L-2
    # migration backfilled stragglers (``amount := sum`` for legacy
    # rows with ``amount IS NULL``) before tightening nullability.
    currency_id: Mapped[int] = mapped_column(
        ForeignKey("currencies.id"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(28, 8), nullable=False)
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
        ForeignKey("users.id"), nullable=True, index=True
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
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    deal_id: Mapped[int | None] = mapped_column(
        ForeignKey("deals.id", ondelete="SET NULL"), nullable=True
    )
    rating: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    author: Mapped[User] = relationship(foreign_keys=[author_id], lazy="selectin")
    target: Mapped[User] = relationship(foreign_keys=[target_id], lazy="selectin")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType), default=NotificationType.system
    )
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text, default="")
    # V11-M-10 — JSONB so downstream consumers can index into the payload
    # without a CAST and so Postgres rejects non-JSON garbage at write
    # time. The notifier still serialises via ``json.dumps`` for the
    # 4 KB cap check; SQLAlchemy converts ``dict`` ↔ ``jsonb`` on its
    # own when the column type is JSONB.
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    recipient: Mapped[User] = relationship(foreign_keys=[recipient_id], lazy="selectin")


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_commission_percent: Mapped[float] = mapped_column(Numeric(5, 2), default=5.0)
    invoice_commission_percent: Mapped[float] = mapped_column(Numeric(5, 2), default=0.0)
    # H-2 — widened from ``Numeric(14, 2)`` to ``Numeric(28, 8)``. The
    # per-currency overrides on ``Currency.min_deposit`` /
    # ``Currency.min_withdraw`` (also ``Numeric(28, 8)``) are what the
    # wallet routers actually enforce; these singleton rows are a
    # global default kept around for admin display. Aligning the
    # precision keeps the admin panel from rendering a value the
    # underlying currency record can hold but the singleton can't.
    min_deposit: Mapped[float] = mapped_column(Numeric(28, 8), default=1.0)
    min_withdraw: Mapped[float] = mapped_column(Numeric(28, 8), default=1.0)
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
    """A darknet forum the user has linked to their profile.

    A-5 (audit v11) — fixated design notes:

    * The entity *is* live, not a stub. ``PATCH /api/me`` replaces the
      collection wholesale (see :func:`routers.me.patch_me`); the
      :class:`schemas.ForumOut` validator enforces ``https://`` and
      length caps; the public profile cards on ``/api/users`` and
      ``/api/users/{username}`` re-serialise this list via
      :func:`serializers.UserOut.from_model`.
    * There is **no** ``/api/forums`` router and the list of
      *approved* forum names is **intentionally hardcoded on the
      frontend** in ``frontend/src/pages/profile/AddForumPage.tsx``
      (``FORUM_OPTIONS``). The trade-off is documented in
      ``ADMIN-PANEL-SPEC.md §14`` — the whitelist evolves slowly
      enough that wiring it through admin-CRUD + a settings table
      would add ceremony without removing any operational pain. If a
      backend whitelist ever lands, it should live on
      :class:`AppSettings` (single-row config table) and surface via
      ``GET /api/forums``; ``AddForumPage`` would then fetch the
      list instead of carrying it inline.
    * The backend currently **does not** validate ``name`` against
      that whitelist either — ``ForumOut._name_ok`` only enforces
      non-empty and ``len ≤ 64``. A user driving the API directly
      can therefore record any forum name; the whitelist is a UX
      affordance for the dropdown, not a security boundary.
    """

    __tablename__ = "forums"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
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
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
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
    # H-2 — match the Deal.amount precision (Numeric(28,8)) so a
    # ``min_deposit`` / ``min_withdraw`` of order 10¹⁰ doesn't silently
    # truncate. Migration ``9c3a4d2e1f08`` widens these columns in DB.
    min_deposit: Mapped[float] = mapped_column(Numeric(28, 8), default=1)
    min_withdraw: Mapped[float] = mapped_column(Numeric(28, 8), default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # anchored regex applied to user-supplied payout addresses
    # in :func:`backend.app.services_wallet.create_withdrawal`. An empty
    # string means "skip the format check" — back-compat for future
    # currencies seeded before their regex is known. The patterns are
    # permissive (catch typos / wrong-network paste), NOT
    # cryptographic; CryptoBot's ``transfer`` API does the checksum
    # validation at payout time.
    address_regex: Mapped[str] = mapped_column(Text, default="", server_default="")


class UserBalance(Base):
    """A user's balance in a specific currency.

    Funds are split into ``amount`` (spendable) and ``locked`` (held
    while a withdrawal is pending or during the 72h cool-down).

    V11-L-20 — at-most-one row per ``(user_id, currency_id)`` pair
    is enforced by the unique constraint
    ``uq_user_balances_user_currency`` (migration
    ``e7a3c1b9d4f6``). Application code in
    ``services_wallet.get_or_create_balance`` /
    ``lock_user_balance`` upserts via
    ``INSERT ... ON CONFLICT (user_id, currency_id) DO NOTHING``
    and relies on this constraint being present.
    """

    __tablename__ = "user_balances"
    __table_args__ = (
        UniqueConstraint("user_id", "currency_id", name="uq_user_balances_user_currency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # M-13: CASCADE on user FK so ``DELETE FROM users`` cascades.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    currency_id: Mapped[int] = mapped_column(ForeignKey("currencies.id"), index=True)
    amount: Mapped[float] = mapped_column(Numeric(28, 8), default=0)
    locked: Mapped[float] = mapped_column(Numeric(28, 8), default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="selectin")
    currency: Mapped[Currency] = relationship(foreign_keys=[currency_id], lazy="selectin")


class WalletDeposit(Base):
    """A CryptoBot invoice issued for a wallet top-up."""

    __tablename__ = "wallet_deposits"
    __table_args__ = (
        # Mirrors the ``ck_wallet_deposits_purpose_known`` CHECK
        # constraint added in migration ``t2b3c4d5e6f7`` — see that
        # revision for the rationale. The closed set matches the
        # ``WalletDepositCreateReq.purpose`` ``Literal`` in
        # ``backend/app/schemas.py``.
        CheckConstraint(
            "purpose IN ('wallet', 'trust')",
            name="ck_wallet_deposits_purpose_known",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    currency_id: Mapped[int] = mapped_column(ForeignKey("currencies.id"), index=True)
    amount: Mapped[float] = mapped_column(Numeric(28, 8))
    provider: Mapped[WalletDepositProvider] = mapped_column(
        Enum(WalletDepositProvider, name="walletdepositprovider"),
        default=WalletDepositProvider.cryptobot,
    )
    provider_invoice_id: Mapped[str] = mapped_column(String(256), index=True)
    pay_url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[WalletDepositStatus] = mapped_column(
        Enum(WalletDepositStatus), default=WalletDepositStatus.pending
    )
    # Routing tag for ``services_wallet.credit_deposit``. ``"wallet"``
    # (the default) credits the standard per-currency ``UserBalance``
    # used to fund deals / fund withdrawals. ``"trust"`` credits the
    # caller's ``User.trust_deposit_balance`` instead — that balance
    # has no spend / withdraw path (lock-in by design) and surfaces
    # publicly as ``deposit`` on the user card. Plain ``String`` (no
    # Postgres enum) to avoid ``ALTER TYPE ADD VALUE`` if we ever add
    # a third purpose; the application layer enforces the closed set
    # via the ``WalletDepositCreateReq.purpose`` ``Literal``.
    purpose: Mapped[str] = mapped_column(String(16), default="wallet", server_default="wallet")
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
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    currency_id: Mapped[int] = mapped_column(ForeignKey("currencies.id"), index=True)
    amount: Mapped[float] = mapped_column(Numeric(28, 8))
    address: Mapped[str] = mapped_column(String(256))
    status: Mapped[WalletWithdrawStatus] = mapped_column(
        Enum(WalletWithdrawStatus), default=WalletWithdrawStatus.pending
    )
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
    # H-2 — Numeric(28,8) so treasury payouts match the rest of the
    # money ledger and don't truncate at the 10¹⁰ scale.
    amount: Mapped[float] = mapped_column(Numeric(28, 8))
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
    # A-6 — cohort filters that compose with the existing role / activity
    # filters. ``created_after`` / ``created_before`` match the user's
    # ``User.created_at`` (the broadcast sends to users registered inside
    # the inclusive window). ``language`` is matched case-insensitively
    # against ``User.language_code`` so an admin can ship a message in
    # Russian to ``ru`` users without picking up the ``en`` cohort.
    audience_created_after: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    audience_created_before: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    audience_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
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
    # PR-H (L-10) — soft-delete tombstone. ``None`` means live;
    # ``DELETE /api/admin/broadcasts/:id`` stamps ``utcnow()`` and
    # the list endpoint filters those rows out. Keeping the row
    # preserves the FK target the admin audit log points at.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

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
