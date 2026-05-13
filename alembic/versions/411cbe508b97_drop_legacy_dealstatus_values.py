"""drop legacy DealStatus values

Removes the five legacy enum values left over from the pre-P3.3 SQLite era:
``wait_confirm``, ``confirmed``, ``success``, ``failed``, ``arbitrage``. P3.3
wiped the SQLite-era data on the way to Postgres so there is nothing left
to migrate — these values are pure dead code.

Postgres does not support ``ALTER TYPE ... DROP VALUE``, so we juggle a
shadow enum: create the new one, swap the column over, drop the old one,
rename the new one back to ``dealstatus``.

Revision ID: 411cbe508b97
Revises: b8adfad43818
Create Date: 2026-05-13 17:30:00.000000
"""

from __future__ import annotations

from typing import Sequence

from alembic import op

revision: str = "411cbe508b97"
down_revision: str | None = "b8adfad43818"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CURRENT_VALUES = (
    "cancelled",
    "pending_confirmation",
    "pending_payment",
    "in_progress",
    "completed",
    "arbitration",
    "resolved_for_buyer",
    "resolved_for_seller",
    "pending_cancellation",
    "cancelled_for_inactivity",
)

_LEGACY_VALUES = (
    "wait_confirm",
    "confirmed",
    "success",
    "failed",
    "arbitrage",
)


def upgrade() -> None:
    new_values = ", ".join(f"'{v}'" for v in _CURRENT_VALUES)
    op.execute(f"CREATE TYPE dealstatus_new AS ENUM ({new_values})")
    op.execute(
        "ALTER TABLE deals "
        "ALTER COLUMN status DROP DEFAULT, "
        "ALTER COLUMN status TYPE dealstatus_new USING status::text::dealstatus_new, "
        "ALTER COLUMN status SET DEFAULT 'pending_confirmation'::dealstatus_new"
    )
    op.execute("DROP TYPE dealstatus")
    op.execute("ALTER TYPE dealstatus_new RENAME TO dealstatus")


def downgrade() -> None:
    all_values = ", ".join(f"'{v}'" for v in (*_CURRENT_VALUES, *_LEGACY_VALUES))
    op.execute(f"CREATE TYPE dealstatus_new AS ENUM ({all_values})")
    op.execute(
        "ALTER TABLE deals "
        "ALTER COLUMN status DROP DEFAULT, "
        "ALTER COLUMN status TYPE dealstatus_new USING status::text::dealstatus_new, "
        "ALTER COLUMN status SET DEFAULT 'pending_confirmation'::dealstatus_new"
    )
    op.execute("DROP TYPE dealstatus")
    op.execute("ALTER TYPE dealstatus_new RENAME TO dealstatus")
