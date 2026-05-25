"""M-2: add services.currency_id FK

Adds an optional ``currency_id`` column to the ``services`` table so
each service can declare its pricing currency explicitly instead of
assuming USD. NULL means "USD" (backward-compatible default).

Revision ID: s1a2b3c4d5e6
Revises: r9a3b6c2d8e1
Create Date: 2026-05-20 13:00:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "s1a2b3c4d5e6"
down_revision: str | None = "r9a3b6c2d8e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "services",
        sa.Column("currency_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_services_currency_id", "services", ["currency_id"])
    op.create_foreign_key(
        "fk_services_currency_id",
        "services",
        "currencies",
        ["currency_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_services_currency_id", "services", type_="foreignkey")
    op.drop_index("ix_services_currency_id", table_name="services")
    op.drop_column("services", "currency_id")
