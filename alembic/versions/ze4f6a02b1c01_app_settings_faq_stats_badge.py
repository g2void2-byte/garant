"""Add AppSettings.faq_stats_badge_enabled toggle.

Controls whether the public ``/faq`` page renders the StatsBadge
component (total users / deals / USD volume). Defaults to ``False``
so each environment opts in explicitly.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "ze4f6a02b1c01"
down_revision: Union[str, None] = "zd3e4f6a02b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "faq_stats_badge_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "faq_stats_badge_enabled")
