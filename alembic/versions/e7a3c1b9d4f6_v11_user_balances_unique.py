"""V11-L-20 — unique (user_id, currency_id) on user_balances.

Pre-fix the schema had no constraint preventing two concurrent
``get_or_create_balance`` calls from each inserting a fresh row for
the same ``(user_id, currency_id)`` pair. The application code
assumed at-most-one row per pair (e.g. ``lock_user_balance`` does
``select(...).with_for_update()`` and ``scalar_one_or_none``), so a
duplicate row would either crash with ``MultipleResultsFound`` or,
worse, silently split a user's balance across two rows depending on
which one the next read happened to lock.

The migration:

1. Collapses any pre-existing duplicates by summing ``amount`` and
   ``locked`` into the lowest-id row, then deleting the others.
   This is a one-shot reconciliation: on a clean DB the DELETE is a
   no-op; on a hot DB that has already raced, it preserves the
   user's total balance rather than discarding half of it.
2. Adds the unique constraint so the new
   ``INSERT ... ON CONFLICT (user_id, currency_id) DO NOTHING`` in
   ``services_wallet`` has a target to conflict against — and so
   future regressions of the kind this fix exists to prevent fail
   fast at the DB instead of silently corrupting balances.

Revision ID: e7a3c1b9d4f6
Revises: d2a7c9b5e4f1
Create Date: 2026-05-16 21:50:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7a3c1b9d4f6"
down_revision: str | None = "d2a7c9b5e4f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # Step 1 — fold every duplicate (user_id, currency_id) group into
    # the row with the lowest id. We sum the amounts / locked so a
    # user who happened to have funds split across the two duplicate
    # rows ends up with the correct total on the surviving row. On a
    # clean DB the CTE matches zero groups and both statements are
    # no-ops.
    bind.execute(
        sa.text(
            """
            WITH grouped AS (
                SELECT
                    user_id,
                    currency_id,
                    MIN(id) AS keep_id,
                    SUM(amount) AS total_amount,
                    SUM(locked) AS total_locked
                FROM user_balances
                GROUP BY user_id, currency_id
                HAVING COUNT(*) > 1
            )
            UPDATE user_balances ub
            SET amount = g.total_amount,
                locked = g.total_locked
            FROM grouped g
            WHERE ub.id = g.keep_id
            """
        )
    )
    bind.execute(
        sa.text(
            """
            DELETE FROM user_balances ub
            USING (
                SELECT user_id, currency_id, MIN(id) AS keep_id
                FROM user_balances
                GROUP BY user_id, currency_id
                HAVING COUNT(*) > 1
            ) g
            WHERE ub.user_id = g.user_id
              AND ub.currency_id = g.currency_id
              AND ub.id <> g.keep_id
            """
        )
    )

    # Step 2 — install the constraint. Named explicitly so the
    # application code's ON CONFLICT target stays stable across DBs.
    op.create_unique_constraint(
        "uq_user_balances_user_currency",
        "user_balances",
        ["user_id", "currency_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_user_balances_user_currency",
        "user_balances",
        type_="unique",
    )
