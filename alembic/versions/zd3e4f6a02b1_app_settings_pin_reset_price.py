"""Add AppSettings.pin_reset_price_usd for the paid PIN-reset flow.

Users who forget their PIN see a modal with this price and can pay
from their fiat balance to receive a fresh 6-digit reset code. The
price is stored on ``app_settings`` so the admin panel can change it
without a deploy. Default 3 (USD) — matches the spec.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "zd3e4f6a02b1"
down_revision: Union[str, None] = "zc2d3e4f6a01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "pin_reset_price_usd",
            sa.Numeric(28, 8),
            nullable=False,
            server_default="3",
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "pin_reset_price_usd")
