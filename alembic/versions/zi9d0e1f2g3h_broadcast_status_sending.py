"""Allow in-progress broadcast status.

Revision ID: zi9d0e1f2g3h
Revises: zh8c9d0e1f2g
Create Date: 2026-06-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "zi9d0e1f2g3h"
down_revision: str | Sequence[str] | None = "zh8c9d0e1f2g"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_broadcasts_status_known", "broadcasts", type_="check")
    op.create_check_constraint(
        "ck_broadcasts_status_known",
        "broadcasts",
        "status IN ('draft', 'sending', 'sent')",
    )


def downgrade() -> None:
    op.execute("UPDATE broadcasts SET status = 'sent' WHERE status = 'sending'")
    op.drop_constraint("ck_broadcasts_status_known", "broadcasts", type_="check")
    op.create_check_constraint(
        "ck_broadcasts_status_known",
        "broadcasts",
        "status IN ('draft', 'sent')",
    )
