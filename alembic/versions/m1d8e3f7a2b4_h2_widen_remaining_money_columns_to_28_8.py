"""H-2 — widen the remaining ``Numeric(14, 2)`` money columns to ``Numeric(28, 8)``.

Revision ID: m1d8e3f7a2b4
Revises: l2c1d3e5f7a9
Create Date: 2026-05-18 00:55:00.000000

V12-I11 — contract reminders:

V5-E-1 — irreversible data loss on downgrade

Companion migration to ``9c3a4d2e1f08`` (which widened the per-currency
ledger columns: ``user_balances`` / ``wallet_deposits`` /
``wallet_withdrawals`` / ``treasury_withdrawals`` / ``currencies``).
This one finishes the H-2 sweep by widening the **five** remaining
``Numeric(14, 2)`` money columns the audit flagged:

* ``users.deposit_total`` — admin-editable lifetime deposit aggregate
  surfaced on the profile screen. Pre-fix a satoshi-scale top-up
  (USDT @ 8 fractional digits) truncated to 2 digits on write.
* ``services.price`` / ``services.deposit`` — per-service catalogue
  figures the buyer copies into ``Deal.amount`` when a deal
  materialises. ``Deal.amount`` already uses ``Numeric(28, 8)`` so a
  service priced at ``0.12345678`` USDT was silently rounded to
  ``0.12`` at the catalogue layer before ever reaching the deal.
* ``app_settings.min_deposit`` / ``app_settings.min_withdraw`` — the
  global default thresholds. The wallet routers actually enforce the
  per-currency overrides on ``currencies.min_deposit`` /
  ``currencies.min_withdraw`` (also ``Numeric(28, 8)``), but the
  admin panel renders the singleton row; pre-fix it could not display
  a threshold the currency record was able to hold.

After this migration **every per-currency money column in the schema**
uses the canonical ``Numeric(28, 8)`` shape (``backend.app.money:
MONEY_PRECISION`` / ``MONEY_SCALE``). The matching ORM declarations in
``backend/app/models.py`` were widened in the same commit.

Postgres rewrites every row of the affected tables under an
``AccessExclusiveLock`` (``ALTER COLUMN TYPE`` has no ``CONCURRENTLY``
form for ``Numeric`` precision changes). ``users`` is the only table
in this set that can grow unboundedly; the migration window is in the
seconds-range at our current scale and short enough that the brief
lock is acceptable. ``services`` and ``app_settings`` are both small.

Downgrade narrows the columns back to ``Numeric(14, 2)``. If any row
written *after* the upgrade has an integer part > 10¹² or a 3rd+
fractional digit, Postgres raises ``numeric field overflow`` and
aborts the downgrade — V5-E-1 contract: the operator must reconcile
or archive those rows before re-narrowing. The marker line above is
matched by
``tests/test_v5_d_e_bucket.py::test_destructive_migrations_document_irreversible_data_loss``.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m1d8e3f7a2b4"
down_revision: Union[str, None] = "l2c1d3e5f7a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column) pairs — kept as a tuple so upgrade() and downgrade()
# iterate the same list and we don't drift the two sides. The audit
# (AUDIT-remaining-v7.md §H-2) identified exactly these five
# columns as the lagging ``Numeric(14, 2)`` declarations.
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("users", "deposit_total"),
    ("services", "price"),
    ("services", "deposit"),
    ("app_settings", "min_deposit"),
    ("app_settings", "min_withdraw"),
)


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Numeric(precision=14, scale=2),
            type_=sa.Numeric(precision=28, scale=8),
            existing_nullable=False,
        )


def downgrade() -> None:
    # V5-E-1: any value whose integer part exceeds 10¹² (the
    # ``Numeric(14, 2)`` precision - scale headroom) or whose 3rd+
    # fractional digit is non-zero will fail this downgrade with
    # ``numeric field overflow``. The operator must archive / reconcile
    # such rows before running ``alembic downgrade``.
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Numeric(precision=28, scale=8),
            type_=sa.Numeric(precision=14, scale=2),
            existing_nullable=False,
        )
