"""app_settings: CHECK deal_commission_percent BETWEEN 0 AND 100

Audit v3 L-3 — ``Numeric(5, 2)`` accepts up to 999.99.  An admin who
accidentally sets the commission to 500 % would burn user balances on
the next ``finish_deal``.  The CHECK constraint caps the column to the
sane [0, 100] range at the database level.

Revision ID: z8f9a0b1c2d3
Revises: y7e8f9a0b1c2
Create Date: 2026-05-23 17:00:00.000000
"""

from __future__ import annotations

from typing import Sequence

from alembic import op

revision: str = "z8f9a0b1c2d3"
down_revision: str | None = "y7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_app_settings_deal_commission_pct_range",
        "app_settings",
        "deal_commission_percent BETWEEN 0 AND 100",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_app_settings_deal_commission_pct_range",
        "app_settings",
        type_="check",
    )
