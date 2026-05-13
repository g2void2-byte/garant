"""Admin PR-A: audit log + user ban/freeze/IP fields

Adds the bookkeeping needed by the admin panel:

1. New ``admin_audit_log`` table — every admin action writes a row with
   actor, target, reason (optional), payload diff, and ip/timestamp.
2. New columns on ``users``:

   * ``is_banned`` / ``ban_reason`` — soft ban (user can browse but
     cannot create deals/services, cannot withdraw).
   * ``is_frozen`` / ``freeze_reason`` — balance freeze (deposits
     allowed, no spending or withdrawals).
   * ``last_ip`` / ``last_login_at`` / ``login_count`` — passive
     fingerprint of the most-recent connection. Used by the admin
     "Аудит и безопасность" tab and by anti-abuse heuristics later.

Note: we deliberately *keep* ``is_moderator`` even though the admin
panel only acknowledges admin/arbiter — dropping a populated boolean
column is too risky and the field stays useful as a soft tag.

Revision ID: 821c481a6fa5
Revises: 2f4b9a13c81d
Create Date: 2026-05-13 23:00:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "821c481a6fa5"
down_revision: str | None = "2f4b9a13c81d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_banned", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("ban_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("is_frozen", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("freeze_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("is_vip", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("last_ip", sa.String(length=45), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("login_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("deposit_total", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("rating_manual", sa.Numeric(3, 2), nullable=True),
    )
    op.add_column(
        "services",
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "services",
        sa.Column("deals_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "services",
        sa.Column("deposit", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "services",
        sa.Column("rating_manual", sa.Numeric(3, 2), nullable=True),
    )

    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "actor_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("action", sa.String(length=64), nullable=False, index=True),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("admin_audit_log")
    op.drop_column("services", "rating_manual")
    op.drop_column("services", "deposit")
    op.drop_column("services", "deals_count")
    op.drop_column("services", "views")
    op.drop_column("users", "rating_manual")
    op.drop_column("users", "deposit_total")
    op.drop_column("users", "login_count")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "last_ip")
    op.drop_column("users", "is_vip")
    op.drop_column("users", "freeze_reason")
    op.drop_column("users", "is_frozen")
    op.drop_column("users", "ban_reason")
    op.drop_column("users", "is_banned")
