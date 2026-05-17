"""L-2 — retire legacy Deal.sum / tighten amount + currency_id NOT NULL.

Revision ID: l2c1d3e5f7a9
Revises: h1a2b3c4d5e6
Create Date: 2026-05-17 22:30:00.000000

Irreversible: yes

V12-I11 — contract reminders:

V5-E-1 — irreversible data loss on downgrade

The pre-multi-currency platform stored each deal's principal in a
single USD-only ``deals.sum`` ``Numeric(14,2)`` column. PR-3 added
the multi-currency tuple ``(deals.currency_id, deals.amount,
deals.commission_amount)`` and H-1 backfilled every legacy
``currency_id IS NULL`` row to ``USDT``. After H-1 the two columns
carried duplicate information for every live row — ``Deal.amount``
was the canonical numeric and ``Deal.sum`` was a backward-compat
shadow.

L-2 retires the shadow:

1. Backfill any ``deals.amount IS NULL`` row from ``deals.sum`` so
   the canonical column is filled before the NOT NULL constraint
   goes on. H-1 only backfilled ``currency_id``; ``amount`` was
   left nullable for the same "schema-safety during stalled
   migration" reason. Production rows have had ``amount`` written
   by every code path since PR-3, but the meta-fix runs the
   ``amount := sum WHERE amount IS NULL`` pass anyway so a stale
   environment can still upgrade cleanly.
2. ``ALTER COLUMN amount SET NOT NULL`` on ``deals``.
3. ``ALTER COLUMN currency_id SET NOT NULL`` on ``deals``.
4. ``DROP COLUMN sum`` on ``deals``.

Pre-flight notes (from the L-2 audit §2):

* This migration assumes H-1 has already run — every legacy row
  with ``currency_id IS NULL`` must have been folded into USDT
  before the NOT NULL constraint is added. The migration fails
  loudly with ``RuntimeError`` if any such row is still present.
* Production rows where both ``deals.amount`` and ``deals.sum``
  are ``NULL`` should not exist (the legacy column was NOT NULL
  pre-PR-3); the backfill is defensive only.

Downgrade is intentionally not implemented — once ``deals.sum`` is
dropped, restoring the pre-L-2 state requires the operator to roll
back to a database snapshot taken before the migration. The
matching contract test
``tests/test_v5_d_e_bucket.py::test_destructive_migrations_document_irreversible_data_loss``
grep-matches the marker above and will fail if it is removed.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "l2c1d3e5f7a9"
down_revision: Union[str, None] = "h1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- pre-flight: H-1 must have run ------------------------------------
    # If any deal still has ``currency_id IS NULL`` we cannot tighten the
    # NOT NULL constraint without losing the row. H-1 already backfilled
    # every such row to USDT; failing loudly here surfaces a missed
    # migration ordering rather than silently dropping rows.
    legacy_null_currency = bind.execute(
        sa.text("SELECT COUNT(*) FROM deals WHERE currency_id IS NULL")
    ).scalar_one()
    if legacy_null_currency:
        raise RuntimeError(
            "L-2 migration found "
            f"{legacy_null_currency} deals with currency_id IS NULL. "
            "Run the H-1 migration (h1a2b3c4d5e6) first; it backfills "
            "legacy USD-only deals to USDT before L-2 tightens the column."
        )

    # --- step 1: backfill amount from the legacy sum column --------------
    # Defensive: PR-3+ code paths always populate ``amount``, but a row
    # written by an old service can theoretically have ``amount IS NULL``
    # while ``sum`` still holds the original Numeric(14,2) value. Copy
    # the value across before the NOT NULL constraint goes on.
    op.execute(sa.text("UPDATE deals SET amount = sum WHERE amount IS NULL"))

    # --- step 2: tighten ``amount`` to NOT NULL --------------------------
    op.alter_column("deals", "amount", existing_type=sa.Numeric(28, 8), nullable=False)

    # --- step 3: tighten ``currency_id`` to NOT NULL ---------------------
    op.alter_column("deals", "currency_id", existing_type=sa.Integer(), nullable=False)

    # --- step 4: drop the legacy Numeric(14,2) ``sum`` column -----------
    op.drop_column("deals", "sum")


def downgrade() -> None:
    # L-2 is intentionally one-way. ``deals.sum`` has been dropped and
    # the NOT NULL constraints on ``deals.amount`` / ``deals.currency_id``
    # were tightened on top of an unbounded production dataset. Restoring
    # the pre-L-2 state requires rolling back the database from a
    # snapshot taken before the migration ran; there is no in-place
    # reverse path that reconstructs the legacy USD column without
    # losing every multi-currency row written between H-1 and L-2.
    raise RuntimeError(
        "L-2 (l2c1d3e5f7a9) is irreversible. Restore the database from a "
        "pre-L-2 snapshot to roll back."
    )
