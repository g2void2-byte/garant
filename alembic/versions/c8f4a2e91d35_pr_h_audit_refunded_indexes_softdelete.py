"""PR-H audit fixes: ``refunded`` deposit status, analytics indexes, broadcast soft-delete.

Bundles three orthogonal schema changes flagged by the audit so they
ship in a single migration:

* **M-16** — add a ``refunded`` value to the ``walletdepositstatus``
  enum. The admin refund endpoint was setting ``status='expired'`` for
  reversed deposits, which conflated CryptoBot-side expiry with an
  admin-initiated reversal in the UI badge + the analytics filters.
  Postgres has no ``ALTER TYPE ... DROP VALUE`` so we go through a
  shadow type to keep the schema rebuild deterministic.

* **L-9** — btree indexes on the columns the ``GET
  /api/admin/analytics/series`` / ``top-arbiters`` queries scan when a
  board has more than a few hundred rows: ``users.last_login_at``,
  ``deals.completed_at``, ``deals.arbitration_resolved_by``,
  ``wallet_deposits.paid_at``. ``users.created_at`` and
  ``deals.created_at`` already had indexes from the initial schema.

* **L-10** — ``broadcasts.deleted_at`` for soft-delete. The current
  ``DELETE /api/admin/broadcasts/:id`` issues a real row delete, which
  also removes the audit reference (the ``admin_audit_log`` row still
  points at a now-missing row). Soft-delete keeps the broadcast row
  around so the audit log stays joinable, and lets us future-proof
  the ``GET ...`` list with a ``WHERE deleted_at IS NULL`` filter.

Revision ID: c8f4a2e91d35
Revises: 9f3c1a0b8e21
Create Date: 2026-05-14 21:15:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c8f4a2e91d35"
down_revision: str | None = "9f3c1a0b8e21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── M-16 ──────────────────────────────────────────────
    # Add ``refunded`` to ``walletdepositstatus``. Same swap-shadow
    # idiom used by ``411cbe508b97`` to drop legacy DealStatus values.
    op.execute(
        "CREATE TYPE walletdepositstatus_new AS ENUM ('pending', 'paid', 'expired', 'refunded')"
    )
    op.execute(
        "ALTER TABLE wallet_deposits "
        "ALTER COLUMN status TYPE walletdepositstatus_new "
        "USING status::text::walletdepositstatus_new"
    )
    op.execute("DROP TYPE walletdepositstatus")
    op.execute("ALTER TYPE walletdepositstatus_new RENAME TO walletdepositstatus")

    # ── L-9 ──────────────────────────────────────────────
    # Pure btree indexes on the timestamp columns the analytics queries
    # filter / sort by. Tiny boards won't notice; once any table is in
    # the tens of thousands range these turn the ``WHERE ts >= start``
    # scans from sequential to index-range.
    op.create_index("ix_users_last_login_at", "users", ["last_login_at"])
    op.create_index("ix_deals_completed_at", "deals", ["completed_at"])
    op.create_index(
        "ix_deals_arbitration_resolved_by",
        "deals",
        ["arbitration_resolved_by"],
    )
    op.create_index("ix_wallet_deposits_paid_at", "wallet_deposits", ["paid_at"])

    # ── L-10 ─────────────────────────────────────────────
    # ``deleted_at`` is nullable; ``NULL`` means "live". An index on
    # ``deleted_at`` is cheap and lets the list query use an index-only
    # filter; the server fills it in via ``utcnow()`` at delete time.
    op.add_column(
        "broadcasts",
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_broadcasts_deleted_at", "broadcasts", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_broadcasts_deleted_at", table_name="broadcasts")
    op.drop_column("broadcasts", "deleted_at")

    op.drop_index("ix_wallet_deposits_paid_at", table_name="wallet_deposits")
    op.drop_index("ix_deals_arbitration_resolved_by", table_name="deals")
    op.drop_index("ix_deals_completed_at", table_name="deals")
    op.drop_index("ix_users_last_login_at", table_name="users")

    # Revert enum to pre-PR-H values. Any rows currently sitting on
    # ``refunded`` get coerced back to ``expired`` (the value they had
    # before the M-16 fix, so the downgrade matches the pre-PR-H
    # behaviour byte-for-byte).
    op.execute("UPDATE wallet_deposits SET status='expired' WHERE status='refunded'")
    op.execute("CREATE TYPE walletdepositstatus_new AS ENUM ('pending', 'paid', 'expired')")
    op.execute(
        "ALTER TABLE wallet_deposits "
        "ALTER COLUMN status TYPE walletdepositstatus_new "
        "USING status::text::walletdepositstatus_new"
    )
    op.execute("DROP TYPE walletdepositstatus")
    op.execute("ALTER TYPE walletdepositstatus_new RENAME TO walletdepositstatus")
