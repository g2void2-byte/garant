"""H-2 — widen money Numeric(18,8) columns to Numeric(28,8).

Revision ID: 9c3a4d2e1f08
Revises: c4e7b1d903fa
Create Date: 2026-05-17 13:33:00.000000

V12-I11 — contract reminders:

V5-E-1 — irreversible data loss on downgrade

This migration widens seven money columns from ``Numeric(18,8)`` to
``Numeric(28,8)`` so the per-currency ledger matches the precision
``Deal.amount`` / ``Deal.commission_amount`` already use. Pre-fix a
balance, deposit, withdrawal or treasury payout above 10¹⁰ would
silently truncate on insert (Postgres clamps a value that overflows
``Numeric(18,8)`` and raises only when the integer part exceeds the
precision — the read-modify-write loop on a debit could therefore
quietly drop satoshis on USDT, USDC and other 8-decimal assets at
realistic balances).

Columns touched:

* ``currencies.min_deposit`` / ``currencies.min_withdraw``
* ``user_balances.amount`` / ``user_balances.locked``
* ``wallet_deposits.amount``
* ``wallet_withdrawals.amount``
* ``treasury_withdrawals.amount``

Upgrade rewrites the affected tables under an ``AccessExclusiveLock``
(Postgres can't widen ``Numeric`` precision in place — every row is
re-stored).  The data is preserved exactly: same scale, wider
precision, every existing value is representable.  These tables are
small at our current scale (rows in the low millions, mostly
``wallet_deposits``); the rewrite finishes in seconds on production.
We do **not** wrap the ALTERs in ``CONCURRENTLY`` blocks because
``ALTER COLUMN TYPE`` does not have a concurrent form — operators
should expect a brief lock during the migration window.

Downgrade narrows the columns back to ``Numeric(18,8)``.  If any row
written *after* the upgrade exceeds ``Numeric(18,8)`` (integer part
> 10¹⁰), Postgres raises ``numeric field overflow`` and aborts the
downgrade — V5-E-1 contract: the operator must reconcile / archive
those rows before re-narrowing.  The marker line above is matched by
``tests/test_v5_d_e_bucket.py::test_destructive_migrations_document_irreversible_data_loss``.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c3a4d2e1f08"
down_revision: Union[str, None] = "c4e7b1d903fa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column) pairs — kept as a tuple so upgrade() and downgrade()
# can iterate the same list and we don't drift the two sides.
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("currencies", "min_deposit"),
    ("currencies", "min_withdraw"),
    ("user_balances", "amount"),
    ("user_balances", "locked"),
    ("wallet_deposits", "amount"),
    ("wallet_withdrawals", "amount"),
    ("treasury_withdrawals", "amount"),
)


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Numeric(precision=18, scale=8),
            type_=sa.Numeric(precision=28, scale=8),
            existing_nullable=False,
        )


def downgrade() -> None:
    # V5-E-1: any value whose integer part exceeds 10¹⁰ will fail this
    # downgrade with ``numeric field overflow``. The operator must
    # archive / reconcile such rows before running ``alembic downgrade``.
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Numeric(precision=28, scale=8),
            type_=sa.Numeric(precision=18, scale=8),
            existing_nullable=False,
        )
