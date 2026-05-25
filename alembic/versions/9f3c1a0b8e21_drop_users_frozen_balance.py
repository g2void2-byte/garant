"""Drop the legacy ``users.frozen_balance`` column.

The column dates back to the original single-currency USD wallet. The
multi-currency rewrite moved escrow holds into ``user_balances`` rows
(``UserBalance.amount`` minus the deal-locked aggregates), and the
"lifetime deposit" surface used by the public profile / Continental
search filter was already migrated to ``users.deposit_total`` (an
admin-panel-maintained value). The three remaining readers
(``serializers.user_to_out``, ``routers/users.list_users``, and
``bot.texts.profile_summary``) still pointed at ``frozen_balance``
even though nothing wrote to it — meaning the public "Депозит" badge
and the ``deposit_min`` filter were both stuck on a value that hadn't
moved since the legacy import. Those readers were repointed at
``deposit_total`` in this same patch; this migration removes the
trailing column.

Down-revision recreates the column with its original NOT NULL +
default-0 shape so a rollback restores schema parity. Note that the
historical values are not preserved — they couldn't be: nothing has
written to the column since the multi-currency cutover, so any
non-zero values are themselves pre-migration artefacts and not part
of the live state. If you ever need them back, restore from a
pre-cutover backup.

V5-E-1 — irreversible data loss on downgrade
--------------------------------------------
This migration drops the ``frozen_balance`` column.  The downgrade
re-adds the column with ``DEFAULT 0`` so the schema shape matches,
but every row's individual ``frozen_balance`` value is lost — it
cannot be recomputed from any other column in the live schema.
Recovery requires a pre-cutover backup as noted above.  Do NOT
downgrade past this revision in production unless the original
values are already considered abandoned.

Revision ID: 9f3c1a0b8e21
Revises: a4e1b8d72f63
Create Date: 2026-05-14 15:00:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9f3c1a0b8e21"
down_revision: str | None = "a4e1b8d72f63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("frozen_balance")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "frozen_balance",
                sa.Numeric(precision=14, scale=2),
                nullable=False,
                server_default="0",
            ),
        )
