"""users.sessions_count for true distinct-session tracking

Audit v3 A-3 — ``login_count`` increments on every
``_LAST_LOGIN_DEBOUNCE`` (5 min) tick, so an SPA-foreground user racks
up ~288 "logins"/day.  This migration adds a sibling
``sessions_count`` column that only ticks when the gap since the last
ping exceeds ``deps._SESSION_GAP`` (30 min) — i.e. a real "came back
after lunch" event.  ``login_count`` is retained for backwards
compatibility with the admin UI's "Логинов" stat.

Revision ID: b1c3d5e7f9a2
Revises: a9b1c2d3e4f5
Create Date: 2026-05-23 18:30:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1c3d5e7f9a2"
down_revision: str | None = "a9b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "sessions_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "sessions_count")
