"""Add ``users.totp_last_counter`` for TOTP replay protection

RFC 6238 §5.2 recommends rejecting a TOTP code once it has been
accepted, so a leaked code can't be replayed inside the same 30-second
window. We persist the last accepted counter (``int(time.time()) //
30``) per user and reject any code whose counter is ``≤`` that.

``-1`` (sentinel) means "no code accepted yet"; any non-negative
counter is treated as the high-water mark.

Revision ID: e5a7c1b3f9d2
Revises: d4f1a8c92e34
Create Date: 2026-05-14 11:36:48.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5a7c1b3f9d2"
down_revision: str | None = "d4f1a8c92e34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "totp_last_counter",
            sa.BigInteger(),
            nullable=False,
            server_default="-1",
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("totp_last_counter")
