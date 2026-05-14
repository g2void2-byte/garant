"""drop the unused ``users.is_moderator`` flag

The moderator role was scrapped from the spec; the column was already
inert (no code path ever sets it to ``true`` after the admin-panel
refactor). Dropping the column to keep the schema honest.

Revision ID: d4f1a8c92e34
Revises: a1c4f8e2b5d7
Create Date: 2026-05-14 16:00:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4f1a8c92e34"
down_revision: str | None = "a1c4f8e2b5d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("is_moderator")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "is_moderator",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
