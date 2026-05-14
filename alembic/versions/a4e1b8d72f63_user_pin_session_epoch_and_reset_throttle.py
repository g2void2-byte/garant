"""Add ``users.pin_session_epoch`` plus per-user PIN-reset throttle columns.

PR-B in the security audit follow-up bundle:

* ``pin_session_epoch`` — every PIN session JWT now carries this value;
  ``admin/users.invalidate_sessions`` bumps it so previously-issued
  tokens fail their ``epoch`` check and stop working before their TTL.
* ``pin_reset_attempts`` + ``pin_reset_window_started_at`` — limit each
  user to 3 reset codes per rolling 24-hour window. Without this the
  reset endpoint could be used as a free DM-spammer / brute-force
  amplifier against the 6-digit code.

Revision ID: a4e1b8d72f63
Revises: f7c2d931a8b4
Create Date: 2026-05-14 13:45:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4e1b8d72f63"
down_revision: str | None = "f7c2d931a8b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "pin_session_epoch",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "pin_reset_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "pin_reset_window_started_at",
            sa.DateTime(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("pin_reset_window_started_at")
        batch.drop_column("pin_reset_attempts")
        batch.drop_column("pin_session_epoch")
