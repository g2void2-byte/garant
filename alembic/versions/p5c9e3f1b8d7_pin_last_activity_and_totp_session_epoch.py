"""pin_last_activity_at + totp_session_epoch

Adds two columns to ``users`` to support:

* **30-minute sliding idle window** for PIN sessions. The legacy
  contract was an absolute 12h JWT TTL; users complained about
  re-entering their PIN on every TMA cold-start even within the
  same hour, and at the same time we wanted an idle expiry so an
  unattended phone with a stale TMA tab doesn't sit logged-in
  forever. ``pin_last_activity_at`` is bumped by
  ``get_current_user`` whenever an authenticated request arrives
  (debounced 30s), and ``require_pin_session`` rejects sessions
  whose last activity is older than
  ``settings.pin_session_ttl_seconds`` (default 30 min).

* **24h TOTP session token**. After a single ``X-Totp-Code`` is
  accepted, the server mints a JWT the frontend caches and replays
  on subsequent admin actions for 24h. ``totp_session_epoch`` is
  embedded in the JWT and bumped on disable / rotation /
  ``invalidate-sessions`` to revoke outstanding sessions
  immediately.

Both columns are nullable / default 0 so existing rows backfill
without a data-migration step.

Revision ID: p5c9e3f1b8d7
Revises: o4b8d2e5a7c1
Create Date: 2026-05-18 21:55:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "p5c9e3f1b8d7"
down_revision: str | None = "o4b8d2e5a7c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "pin_last_activity_at",
            sa.DateTime(),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "totp_session_epoch",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "totp_session_epoch")
    op.drop_column("users", "pin_last_activity_at")
