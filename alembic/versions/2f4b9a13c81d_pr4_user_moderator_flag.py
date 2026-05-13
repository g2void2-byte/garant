"""pr-4: add ``is_moderator`` flag on users

Continental's "Префикс" filter offers three options:
``Администратор`` / ``Модератор`` / ``Арбитр``. Our schema previously only
had ``is_admin`` and ``is_arbiter`` — this migration adds the missing
``is_moderator`` flag so the search filter can target it 1:1.

Revision ID: 2f4b9a13c81d
Revises: c3a7e1f24d12
Create Date: 2026-05-13 22:00:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2f4b9a13c81d"
down_revision: str | None = "c3a7e1f24d12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_moderator",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_moderator")
