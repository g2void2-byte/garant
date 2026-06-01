"""Make account-transfer code hashes unique.

Revision ID: zh8c9d0e1f2g
Revises: zg7b8c9d0e1f2
Create Date: 2026-06-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "zh8c9d0e1f2g"
down_revision: str | Sequence[str] | None = "zg7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM account_transfer_codes
            WHERE consumed_at IS NOT NULL OR expires_at < now()
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM account_transfer_codes older
            USING account_transfer_codes newer
            WHERE older.code_hash = newer.code_hash
              AND older.id < newer.id
            """
        )
    )
    op.execute(sa.text("DROP INDEX IF EXISTS ix_account_transfer_codes_code_hash"))
    op.create_unique_constraint(
        "uq_account_transfer_codes_code_hash",
        "account_transfer_codes",
        ["code_hash"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_account_transfer_codes_code_hash",
        "account_transfer_codes",
        type_="unique",
    )
    op.create_index(
        op.f("ix_account_transfer_codes_code_hash"),
        "account_transfer_codes",
        ["code_hash"],
        unique=False,
    )
