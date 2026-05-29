"""Add admin-editable FAQ stats values to AppSettings.

Three new columns let the admin showcase round/marketing numbers on
the public ``/faq`` page StatsBadge without computing live values:

- ``faq_stats_users``: integer count of users to display.
- ``faq_stats_deals``: integer count of deals to display.
- ``faq_stats_total_usd``: USD volume to display (Numeric(28, 8)).

All default to 0.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "zf6a02b1c01d"
down_revision: Union[str, None] = "ze4f6a02b1c01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "faq_stats_users",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "faq_stats_deals",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "faq_stats_total_usd",
            sa.Numeric(28, 8),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "faq_stats_total_usd")
    op.drop_column("app_settings", "faq_stats_deals")
    op.drop_column("app_settings", "faq_stats_users")
