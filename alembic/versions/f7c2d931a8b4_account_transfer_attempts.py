"""Add ``account_transfer_codes.attempts`` for brute-force protection

A 6-digit ``AccountTransferCode`` (10⁶ keyspace) is shared by *every*
active in-flight transfer in the system: ``confirm_transfer`` looks up
codes by hash across all rows. Without a per-code attempt counter a
caller could enumerate the keyspace and hijack any account that had
issued a transfer. The new column tracks failed attempts and lets the
service consume the code once it crosses a small threshold.

Revision ID: f7c2d931a8b4
Revises: e5a7c1b3f9d2
Create Date: 2026-05-14 12:30:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f7c2d931a8b4"
down_revision: str | None = "e5a7c1b3f9d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "account_transfer_codes",
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("account_transfer_codes") as batch:
        batch.drop_column("attempts")
