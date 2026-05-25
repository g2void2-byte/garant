"""initial schema

Revision ID: 9d0e4d959e65
Revises:
Create Date: 2026-05-13 16:43:49.488563
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9d0e4d959e65"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deal_commission_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("invoice_commission_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("min_deposit", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("min_withdraw", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("inactivity_pending_confirmation_days", sa.Integer(), nullable=False),
        sa.Column("inactivity_pending_cancellation_days", sa.Integer(), nullable=False),
        sa.Column("max_active_services_per_user", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("icon", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_categories_slug"), "categories", ["slug"], unique=True)
    op.create_table(
        "currencies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("network", sa.String(length=32), nullable=False),
        sa.Column("icon_url", sa.Text(), nullable=False),
        sa.Column("decimals", sa.Integer(), nullable=False),
        sa.Column("min_deposit", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("min_withdraw", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_currencies_code"), "currencies", ["code"], unique=True)
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("photo_url", sa.Text(), nullable=True),
        sa.Column("banner_url", sa.Text(), nullable=True),
        sa.Column("balance", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("frozen_balance", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("is_arbiter", sa.Boolean(), nullable=False),
        sa.Column("deals_total", sa.Integer(), nullable=False),
        sa.Column("deals_success", sa.Integer(), nullable=False),
        sa.Column("deals_failed", sa.Integer(), nullable=False),
        sa.Column("deals_arbitrage", sa.Integer(), nullable=False),
        sa.Column("good", sa.Integer(), nullable=False),
        sa.Column("bad", sa.Integer(), nullable=False),
        sa.Column("pin_hash", sa.String(length=255), nullable=True),
        sa.Column("pin_attempts", sa.Integer(), nullable=False),
        sa.Column("pin_locked_until", sa.DateTime(), nullable=True),
        sa.Column("pin_reset_code_hash", sa.String(length=255), nullable=True),
        sa.Column("pin_reset_expires", sa.DateTime(), nullable=True),
        sa.Column("dm_deals", sa.Boolean(), nullable=False),
        sa.Column("dm_deposits", sa.Boolean(), nullable=False),
        sa.Column("dm_system", sa.Boolean(), nullable=False),
        sa.Column("is_anonymous_deals", sa.Boolean(), nullable=False),
        sa.Column("is_hidden_profile", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_tg_user_id"), "users", ["tg_user_id"], unique=True)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
    op.create_table(
        "account_transfer_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_user_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("target_tg_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_account_transfer_codes_code_hash"),
        "account_transfer_codes",
        ["code_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_account_transfer_codes_source_user_id"),
        "account_transfer_codes",
        ["source_user_id"],
        unique=False,
    )
    op.create_table(
        "deals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("buyer_id", sa.Integer(), nullable=False),
        sa.Column("seller_id", sa.Integer(), nullable=False),
        sa.Column("sum", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "pay_commission", sa.Enum("buyer", "seller", name="paycommission"), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum(
                "cancelled",
                "pending_confirmation",
                "pending_payment",
                "in_progress",
                "completed",
                "arbitration",
                "resolved_for_buyer",
                "resolved_for_seller",
                "pending_cancellation",
                "cancelled_for_inactivity",
                "wait_confirm",
                "confirmed",
                "success",
                "failed",
                "arbitrage",
                name="dealstatus",
            ),
            nullable=False,
        ),
        sa.Column("confirm_buyer", sa.Boolean(), nullable=False),
        sa.Column("confirm_seller", sa.Boolean(), nullable=False),
        sa.Column("arbitrage_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("currency_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("commission_amount", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("in_progress_at", sa.DateTime(), nullable=True),
        sa.Column("cancellation_initiator_id", sa.Integer(), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("cancellation_requested_at", sa.DateTime(), nullable=True),
        sa.Column("arbitration_initiator_id", sa.Integer(), nullable=True),
        sa.Column("arbitration_reason", sa.Text(), nullable=True),
        sa.Column("arbitration_resolved_by", sa.Integer(), nullable=True),
        sa.Column("arbitration_resolution", sa.String(length=16), nullable=True),
        sa.Column("arbitration_resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["arbitration_initiator_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["arbitration_resolved_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["buyer_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["cancellation_initiator_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["currency_id"],
            ["currencies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["seller_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_deals_buyer_id"), "deals", ["buyer_id"], unique=False)
    op.create_index(op.f("ix_deals_created_at"), "deals", ["created_at"], unique=False)
    op.create_index(op.f("ix_deals_currency_id"), "deals", ["currency_id"], unique=False)
    op.create_index(op.f("ix_deals_seller_id"), "deals", ["seller_id"], unique=False)
    op.create_index(op.f("ix_deals_status"), "deals", ["status"], unique=False)
    op.create_table(
        "forums",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.Enum("cryptobot", name="invoiceprovider"), nullable=False),
        sa.Column("provider_invoice_id", sa.String(length=256), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "status", sa.Enum("pending", "paid", "expired", name="invoicestatus"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_invoice_id"),
    )
    op.create_table(
        "media",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_media_kind"), "media", ["kind"], unique=False)
    op.create_index(op.f("ix_media_owner_id"), "media", ["owner_id"], unique=False)
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recipient_id", sa.Integer(), nullable=False),
        sa.Column(
            "type", sa.Enum("deals", "deposits", "system", name="notificationtype"), nullable=False
        ),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_notifications_created_at"), "notifications", ["created_at"], unique=False
    )
    op.create_index(op.f("ix_notifications_is_read"), "notifications", ["is_read"], unique=False)
    op.create_index(
        op.f("ix_notifications_recipient_id"), "notifications", ["recipient_id"], unique=False
    )
    op.create_table(
        "services",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("price", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "active", "paused", "banned", name="servicestatus"),
            nullable=False,
        ),
        sa.Column("ban_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_services_status"), "services", ["status"], unique=False)
    op.create_table(
        "user_balances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("currency_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("locked", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["currency_id"],
            ["currencies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_user_balances_currency_id"), "user_balances", ["currency_id"], unique=False
    )
    op.create_index(op.f("ix_user_balances_user_id"), "user_balances", ["user_id"], unique=False)
    op.create_table(
        "wallet_deposits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("currency_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("provider", sa.Enum("cryptobot", name="invoiceprovider"), nullable=False),
        sa.Column("provider_invoice_id", sa.String(length=256), nullable=False),
        sa.Column("pay_url", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "paid", "expired", name="walletdepositstatus"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["currency_id"],
            ["currencies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_wallet_deposits_currency_id"), "wallet_deposits", ["currency_id"], unique=False
    )
    op.create_index(
        op.f("ix_wallet_deposits_provider_invoice_id"),
        "wallet_deposits",
        ["provider_invoice_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wallet_deposits_user_id"), "wallet_deposits", ["user_id"], unique=False
    )
    op.create_table(
        "wallet_withdrawals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("currency_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("address", sa.String(length=256), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "sent", "rejected", name="walletwithdrawstatus"),
            nullable=False,
        ),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["currency_id"],
            ["currencies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_wallet_withdrawals_currency_id"),
        "wallet_withdrawals",
        ["currency_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wallet_withdrawals_user_id"), "wallet_withdrawals", ["user_id"], unique=False
    )
    op.create_table(
        "deal_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("sender_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("attachments_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["deal_id"],
            ["deals.id"],
        ),
        sa.ForeignKeyConstraint(
            ["sender_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_deal_messages_created_at"), "deal_messages", ["created_at"], unique=False
    )
    op.create_index(op.f("ix_deal_messages_deal_id"), "deal_messages", ["deal_id"], unique=False)
    op.create_index(
        op.f("ix_deal_messages_sender_id"), "deal_messages", ["sender_id"], unique=False
    )
    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"],
            ["deals.id"],
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reviews_author_id"), "reviews", ["author_id"], unique=False)
    op.create_index(op.f("ix_reviews_target_id"), "reviews", ["target_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_reviews_target_id"), table_name="reviews")
    op.drop_index(op.f("ix_reviews_author_id"), table_name="reviews")
    op.drop_table("reviews")
    op.drop_index(op.f("ix_deal_messages_sender_id"), table_name="deal_messages")
    op.drop_index(op.f("ix_deal_messages_deal_id"), table_name="deal_messages")
    op.drop_index(op.f("ix_deal_messages_created_at"), table_name="deal_messages")
    op.drop_table("deal_messages")
    op.drop_index(op.f("ix_wallet_withdrawals_user_id"), table_name="wallet_withdrawals")
    op.drop_index(op.f("ix_wallet_withdrawals_currency_id"), table_name="wallet_withdrawals")
    op.drop_table("wallet_withdrawals")
    op.drop_index(op.f("ix_wallet_deposits_user_id"), table_name="wallet_deposits")
    op.drop_index(op.f("ix_wallet_deposits_provider_invoice_id"), table_name="wallet_deposits")
    op.drop_index(op.f("ix_wallet_deposits_currency_id"), table_name="wallet_deposits")
    op.drop_table("wallet_deposits")
    op.drop_index(op.f("ix_user_balances_user_id"), table_name="user_balances")
    op.drop_index(op.f("ix_user_balances_currency_id"), table_name="user_balances")
    op.drop_table("user_balances")
    op.drop_index(op.f("ix_services_status"), table_name="services")
    op.drop_table("services")
    op.drop_index(op.f("ix_notifications_recipient_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_is_read"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_created_at"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_index(op.f("ix_media_owner_id"), table_name="media")
    op.drop_index(op.f("ix_media_kind"), table_name="media")
    op.drop_table("media")
    op.drop_table("invoices")
    op.drop_table("forums")
    op.drop_index(op.f("ix_deals_status"), table_name="deals")
    op.drop_index(op.f("ix_deals_seller_id"), table_name="deals")
    op.drop_index(op.f("ix_deals_currency_id"), table_name="deals")
    op.drop_index(op.f("ix_deals_created_at"), table_name="deals")
    op.drop_index(op.f("ix_deals_buyer_id"), table_name="deals")
    op.drop_table("deals")
    op.drop_index(
        op.f("ix_account_transfer_codes_source_user_id"), table_name="account_transfer_codes"
    )
    op.drop_index(op.f("ix_account_transfer_codes_code_hash"), table_name="account_transfer_codes")
    op.drop_table("account_transfer_codes")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_index(op.f("ix_users_tg_user_id"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_currencies_code"), table_name="currencies")
    op.drop_table("currencies")
    op.drop_index(op.f("ix_categories_slug"), table_name="categories")
    op.drop_table("categories")
    op.drop_table("app_settings")
    # Audit §15.2 — Postgres ENUM types created inline by
    # ``sa.Enum(..., name=...)`` are *not* dropped automatically when
    # the owning table goes away. Without these the next
    # ``alembic upgrade head`` after a full downgrade fails with
    # ``type already exists``. ``IF EXISTS`` keeps the downgrade
    # idempotent across legacy / Postgres-newer revisions that may
    # have already pruned a name.
    op.execute("DROP TYPE IF EXISTS paycommission")
    op.execute("DROP TYPE IF EXISTS dealstatus")
    op.execute("DROP TYPE IF EXISTS invoiceprovider")
    op.execute("DROP TYPE IF EXISTS invoicestatus")
    op.execute("DROP TYPE IF EXISTS notificationtype")
    op.execute("DROP TYPE IF EXISTS servicestatus")
    op.execute("DROP TYPE IF EXISTS walletdepositstatus")
    op.execute("DROP TYPE IF EXISTS walletwithdrawstatus")
