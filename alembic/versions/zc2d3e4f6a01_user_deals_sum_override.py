"""Add User.deals_sum_override for admin-editable "сумма сделок".

Real per-currency volume isn't trivial to aggregate (different
currencies, deleted deals), so we surface a manually-set value that
the admin can override per user. Serializers forward it as
``deals_sum`` in the public/private DTOs; the previous behaviour was
to hard-code ``0`` everywhere.

Numeric(28, 8) matches the rest of the money columns in the schema
(audit H-2). NULL is disallowed — default 0 for every existing row.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "zc2d3e4f6a01"
down_revision: Union[str, None] = "zb1c2d3e4f6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "deals_sum_override",
            sa.Numeric(28, 8),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "deals_sum_override")
