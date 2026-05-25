"""P5 + P10 — drop Treasury + add commission-via-invoice columns.

This migration combines two related schema changes that travel
together in the ``feat/commission-via-invoice`` work:

P5 — Treasury removal
---------------------
* DROP TABLE ``treasury_withdrawals``. The on-platform commission
  accumulator + admin withdraw queue is fully retired; commission is
  now charged at deal-create time through the wallet provider's
  invoice (see :func:`backend.app.services_deals.create_deal_with_topup`).
* DROP COLUMN ``deals.pay_commission``. The legacy buyer/seller
  commission-payer split is no longer meaningful — the platform
  always collects via the deposit invoice.

P10 — commission-via-invoice support
------------------------------------
* ADD COLUMN ``deals.topup_deposit_id`` (FK → ``wallet_deposits.id``,
  ON DELETE SET NULL) — reverse pointer to the deposit invoice issued
  by ``create_deal_with_topup``.
* ADD COLUMN ``deals.commission_paid`` (bool, default ``false``) —
  set when the deposit webhook lands a payment large enough to
  cover the commission share.
* ADD VALUE ``'deal_topup'`` to the ``walletdepositpurpose`` check
  constraint on ``wallet_deposits.purpose``.
* ADD COLUMN ``wallet_deposits.linked_deal_id`` (FK → ``deals.id``,
  ON DELETE SET NULL) — forward pointer to the deal funded by this
  deposit; ``NULL`` for legacy wallet/trust deposits.
* ADD COLUMN ``wallet_deposits.paid_amount`` (``Numeric(28, 8)``) —
  captures the actual amount reported by the provider webhook,
  which may differ from ``amount`` in the under-/over-payment cases.
* ADD VALUE ``'pending_topup'`` to the ``dealstatus`` enum so deals
  awaiting their deposit invoice can sit in a distinct state until
  the webhook arrives.
* ADD COLUMN ``app_settings.pending_topup_expiry_hours`` (int,
  default ``24``) — sweep window for the new
  :func:`backend.app.services_deals.sweep_pending_topup` background
  loop.

Revision ID: za1b2c3d4e5f
Revises: d1b6e2g04c38
Create Date: 2026-05-23 23:10:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "za1b2c3d4e5f"
down_revision: str | None = "d1b6e2g04c38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── P5: drop the treasury table & deals.pay_commission ──────────
    op.drop_table("treasury_withdrawals")
    with op.batch_alter_table("deals") as batch:
        batch.drop_column("pay_commission")

    # ── P10: dealstatus enum gains ``pending_topup`` ────────────────
    # Postgres needs ``ALTER TYPE ... ADD VALUE`` rather than a
    # column-level change. ``IF NOT EXISTS`` keeps reruns idempotent
    # (helpful if a partial migration left the value behind).
    op.execute("ALTER TYPE dealstatus ADD VALUE IF NOT EXISTS 'pending_topup'")

    # ── P10: deals.topup_deposit_id + deals.commission_paid ────────
    with op.batch_alter_table("deals") as batch:
        batch.add_column(
            sa.Column(
                "topup_deposit_id",
                sa.Integer(),
                sa.ForeignKey("wallet_deposits.id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "commission_paid",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
    op.create_index(
        "ix_deals_topup_deposit_id",
        "deals",
        ["topup_deposit_id"],
    )

    # ── P10: wallet_deposits.purpose check constraint widens to
    # accept ``'deal_topup'``. The existing constraint is named
    # ``ck_wallet_deposits_purpose_known`` (see ``models.py``).
    op.execute(
        "ALTER TABLE wallet_deposits DROP CONSTRAINT IF EXISTS ck_wallet_deposits_purpose_known"
    )
    op.create_check_constraint(
        "ck_wallet_deposits_purpose_known",
        "wallet_deposits",
        "purpose IN ('wallet', 'trust', 'deal_topup')",
    )

    # ── P10: wallet_deposits.linked_deal_id + paid_amount ──────────
    with op.batch_alter_table("wallet_deposits") as batch:
        batch.add_column(
            sa.Column(
                "linked_deal_id",
                sa.Integer(),
                sa.ForeignKey("deals.id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "paid_amount",
                sa.Numeric(28, 8),
                nullable=True,
            )
        )
    op.create_index(
        "ix_wallet_deposits_linked_deal_id",
        "wallet_deposits",
        ["linked_deal_id"],
    )

    # ── P10: app_settings.pending_topup_expiry_hours ───────────────
    with op.batch_alter_table("app_settings") as batch:
        batch.add_column(
            sa.Column(
                "pending_topup_expiry_hours",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("24"),
            )
        )


def downgrade() -> None:
    # The downgrade path is best-effort: we re-add the dropped
    # columns/tables with their original shape so the schema is
    # restored, but accrued treasury history (which was already
    # platform-side via the deposit invoices) is not recoverable.
    with op.batch_alter_table("app_settings") as batch:
        batch.drop_column("pending_topup_expiry_hours")

    op.drop_index("ix_wallet_deposits_linked_deal_id", table_name="wallet_deposits")
    with op.batch_alter_table("wallet_deposits") as batch:
        batch.drop_column("paid_amount")
        batch.drop_column("linked_deal_id")

    op.execute(
        "ALTER TABLE wallet_deposits DROP CONSTRAINT IF EXISTS ck_wallet_deposits_purpose_known"
    )
    op.create_check_constraint(
        "ck_wallet_deposits_purpose_known",
        "wallet_deposits",
        "purpose IN ('wallet', 'trust')",
    )

    op.drop_index("ix_deals_topup_deposit_id", table_name="deals")
    with op.batch_alter_table("deals") as batch:
        batch.drop_column("commission_paid")
        batch.drop_column("topup_deposit_id")

    # ``pending_topup`` cannot be dropped from a Postgres enum without
    # the same enum-swap dance that ``411cbe508b97`` does. We leave
    # the value present (harmless leftover) rather than re-running
    # the shadow-enum machinery from a downgrade.

    # Re-add the legacy ``pay_commission`` column with the historical
    # default so the downgraded schema accepts inserts again.
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'paycommission') THEN "
        "CREATE TYPE paycommission AS ENUM ('buyer', 'seller'); "
        "END IF; "
        "END $$;"
    )
    with op.batch_alter_table("deals") as batch:
        batch.add_column(
            sa.Column(
                "pay_commission",
                sa.Enum("buyer", "seller", name="paycommission"),
                nullable=False,
                server_default="buyer",
            )
        )

    op.create_table(
        "treasury_withdrawals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("currency_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(28, 8), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("cryptobot_transfer_id", sa.String(length=64), nullable=True),
        sa.Column("spend_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
