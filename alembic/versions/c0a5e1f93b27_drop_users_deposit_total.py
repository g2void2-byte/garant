"""Drop the legacy ``users.deposit_total`` column.

The column was the admin-editable "lifetime deposit aggregate" — a
manually-maintained figure that paralleled the per-currency ledger
without ever being reconciled against it. The public profile's
``deposit`` badge has been sourced from
:attr:`User.trust_deposit_balance` since Item 12 (the lock-in trust
deposit), so ``deposit_total`` was effectively a write-only column:
the admin "Stats" form could edit it, but no UI surface read it for
end users. Continental's ``deposit_min`` search filter pointed at it,
but the filter has been retired in the same patch (see
``backend/app/routers/users.py``).

This migration drops the column outright. The three remaining
readers (``serializers``, ``bot.texts.profile_summary``,
``bot.sections.profile`` banner) were already repointed at
``trust_deposit_balance``; the admin panel's set-stats endpoint no
longer carries the field; the ``sort=deposit`` ordering on the admin
user list was removed in the same patch.

V5-E-1 — irreversible data loss on downgrade
--------------------------------------------
The downgrade re-adds the column with ``DEFAULT 0`` so the schema
shape matches, but per-row historical values are lost — they cannot
be recomputed from any other live column. Recovery requires a
pre-cutover backup. Do NOT downgrade past this revision in production
unless the original aggregate is already considered abandoned.

Revision ID: c0a5e1f93b27
Revises: b1c3d5e7f9a2
Create Date: 2026-05-23 21:30:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0a5e1f93b27"
down_revision: str | None = "b1c3d5e7f9a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("deposit_total")


def downgrade() -> None:
    # V5-E-1: the downgrade restores the column shape but cannot
    # restore the per-row values. The ``DEFAULT 0`` server-side
    # default mirrors the original column declaration so existing
    # rows are admissible without backfill.
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "deposit_total",
                sa.Numeric(precision=28, scale=8),
                nullable=False,
                server_default="0",
            ),
        )
