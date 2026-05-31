"""Operational ledger, webhook inbox/outbox, rates and approvals.

Revision ID: zg7b8c9d0e1f2
Revises: zf6a02b1c01d
Create Date: 2026-05-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "zg7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "zf6a02b1c01d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "currency_usd_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("currency_id", sa.Integer(), nullable=False),
        sa.Column("usd_rate", sa.Numeric(28, 8), nullable=False),
        sa.Column("source", sa.String(length=64), server_default="manual", nullable=False),
        sa.Column("observed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("currency_id", name="uq_currency_usd_rates_currency_id"),
    )
    op.create_index("ix_currency_usd_rates_currency_id", "currency_usd_rates", ["currency_id"])
    op.create_index("ix_currency_usd_rates_updated_by_id", "currency_usd_rates", ["updated_by_id"])

    op.create_table(
        "wallet_ledger_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("currency_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("provider_event_id", sa.String(length=128), nullable=True),
        sa.Column("amount_before", sa.Numeric(28, 8), server_default="0", nullable=False),
        sa.Column("amount_delta", sa.Numeric(28, 8), server_default="0", nullable=False),
        sa.Column("amount_after", sa.Numeric(28, 8), server_default="0", nullable=False),
        sa.Column("locked_before", sa.Numeric(28, 8), server_default="0", nullable=False),
        sa.Column("locked_delta", sa.Numeric(28, 8), server_default="0", nullable=False),
        sa.Column("locked_after", sa.Numeric(28, 8), server_default="0", nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    for column in (
        "user_id",
        "currency_id",
        "event_type",
        "source_type",
        "source_id",
        "provider_event_id",
        "created_at",
    ):
        op.create_index(f"ix_wallet_ledger_entries_{column}", "wallet_ledger_entries", [column])

    op.create_table(
        "provider_webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("provider_invoice_id", sa.String(length=256), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="received", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), server_default="", nullable=False),
        sa.Column("headers_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("provider", "event_id", name="uq_provider_webhook_events_provider_event"),
    )
    for column in ("provider", "event_id", "event_type", "provider_invoice_id", "status", "created_at"):
        op.create_index(f"ix_provider_webhook_events_{column}", "provider_webhook_events", [column])

    op.create_table(
        "provider_webhook_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("webhook_event_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="ready", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["webhook_event_id"], ["provider_webhook_events.id"], ondelete="CASCADE"),
    )
    for column in ("webhook_event_id", "kind", "status", "next_attempt_at", "created_at"):
        op.create_index(f"ix_provider_webhook_outbox_{column}", "provider_webhook_outbox", [column])

    op.create_table(
        "admin_approval_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("requested_by_id", sa.Integer(), nullable=True),
        sa.Column("approved_by_id", sa.Integer(), nullable=True),
        sa.Column("executed_by_id", sa.Integer(), nullable=True),
        sa.Column("currency_id", sa.Integer(), nullable=True),
        sa.Column("rate_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(28, 8), nullable=True),
        sa.Column("amount_usd_estimate", sa.Numeric(28, 8), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["currency_id"], ["currencies.id"]),
        sa.ForeignKeyConstraint(["executed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rate_id"], ["currency_usd_rates.id"]),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    for column in (
        "action",
        "target_type",
        "target_id",
        "status",
        "requested_by_id",
        "approved_by_id",
        "executed_by_id",
        "created_at",
    ):
        op.create_index(f"ix_admin_approval_requests_{column}", "admin_approval_requests", [column])


def downgrade() -> None:
    for column in (
        "created_at",
        "executed_by_id",
        "approved_by_id",
        "requested_by_id",
        "status",
        "target_id",
        "target_type",
        "action",
    ):
        op.drop_index(f"ix_admin_approval_requests_{column}", table_name="admin_approval_requests")
    op.drop_table("admin_approval_requests")

    for column in ("created_at", "next_attempt_at", "status", "kind", "webhook_event_id"):
        op.drop_index(f"ix_provider_webhook_outbox_{column}", table_name="provider_webhook_outbox")
    op.drop_table("provider_webhook_outbox")

    for column in ("created_at", "status", "provider_invoice_id", "event_type", "event_id", "provider"):
        op.drop_index(f"ix_provider_webhook_events_{column}", table_name="provider_webhook_events")
    op.drop_table("provider_webhook_events")

    for column in (
        "created_at",
        "provider_event_id",
        "source_id",
        "source_type",
        "event_type",
        "currency_id",
        "user_id",
    ):
        op.drop_index(f"ix_wallet_ledger_entries_{column}", table_name="wallet_ledger_entries")
    op.drop_table("wallet_ledger_entries")

    op.drop_index("ix_currency_usd_rates_updated_by_id", table_name="currency_usd_rates")
    op.drop_index("ix_currency_usd_rates_currency_id", table_name="currency_usd_rates")
    op.drop_table("currency_usd_rates")
