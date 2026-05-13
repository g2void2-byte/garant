"""Admin PR-CDE: 2FA cols, settings extensions, treasury/broadcast tables

Adds the bookkeeping needed by the finance/settings/broadcast modules:

1. ``users.totp_secret`` / ``users.totp_enabled`` — TOTP shared secret
   and enabled flag. Used to gate treasury withdrawal and user delete
   via the ``/api/auth/2fa/verify`` endpoint.
2. ``app_settings`` extensions:
   * ``vip_commission_percent`` — VIP override (``-1`` = no override).
   * ``maintenance_enabled`` / ``maintenance_message`` — global
     maintenance switch; blocks all non-admin writes when enabled.
   * ``auto_withdraw_enabled`` — when on, ``/api/admin/withdrawals``
     auto-pushes approved rows through CryptoBot Transfer.
3. New ``treasury_withdrawals`` table — admin payouts of accumulated
   commission to an external address.
4. New ``broadcasts`` table — admin-authored in-app/DM notifications
   with audience filters.

Revision ID: a1c4f8e2b5d7
Revises: 821c481a6fa5
Create Date: 2026-05-14 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1c4f8e2b5d7"
down_revision: str | None = "821c481a6fa5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("totp_secret", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.add_column(
        "app_settings",
        sa.Column(
            "vip_commission_percent",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="-1",
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "maintenance_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "maintenance_message",
            sa.Text(),
            nullable=False,
            server_default="Сервис на технических работах. Зайдите позже.",
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "auto_withdraw_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.create_table(
        "treasury_withdrawals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "actor_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "currency_id",
            sa.Integer(),
            sa.ForeignKey("currencies.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("amount", sa.Numeric(18, 8), nullable=False),
        sa.Column("address", sa.String(length=256), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="sent",
            index=True,
        ),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("cryptobot_transfer_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
    )

    op.create_table(
        "broadcasts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "actor_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("deeplink", sa.Text(), nullable=True),
        sa.Column("audience_role", sa.String(length=16), nullable=True),
        sa.Column("audience_active_days", sa.Integer(), nullable=True),
        sa.Column("audience_min_deals", sa.Integer(), nullable=True),
        sa.Column(
            "dispatch_inapp",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "dispatch_dm",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="sent",
            index=True,
        ),
        sa.Column("total_recipients", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("broadcasts")
    op.drop_table("treasury_withdrawals")
    op.drop_column("app_settings", "auto_withdraw_enabled")
    op.drop_column("app_settings", "maintenance_message")
    op.drop_column("app_settings", "maintenance_enabled")
    op.drop_column("app_settings", "vip_commission_percent")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
