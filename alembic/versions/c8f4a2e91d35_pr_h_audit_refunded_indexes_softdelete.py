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

V5-E-1 — irreversible data loss on downgrade
--------------------------------------------
The downgrade coerces every ``status='refunded'`` row back to
``status='expired'`` before recreating the legacy enum, because the
pre-PR-H enum has no ``refunded`` value.  After downgrade, there is
no live column on ``wallet_deposits`` that distinguishes "admin
manually refunded this deposit" from "Crypto Pay expired it
naturally": the two states collapse to the same value, and the
distinction is lost.  Recovery requires a pre-downgrade backup of
``wallet_deposits.status``.  Do NOT downgrade this revision on
production without confirming the operations team is okay with that
loss of audit fidelity.

V5-E-2 — ``CREATE INDEX CONCURRENTLY``
--------------------------------------
The L-9 btree indexes target ``users`` / ``deals`` /
``wallet_deposits`` — tables that grow continuously.  The plain
``CREATE INDEX`` form takes an ``ACCESS EXCLUSIVE`` lock for the
duration of the scan, which on a multi-million-row table parks
every concurrent write on those tables for the build window.  We
wrap each index in :func:`alembic.runtime.migration.MigrationContext.autocommit_block`
so they go through ``CREATE INDEX CONCURRENTLY``, which takes only
``SHARE UPDATE EXCLUSIVE`` (concurrent reads + writes allowed).
``IF NOT EXISTS`` covers a partial run where one of the indexes
already built and another didn't, so a retry-driven re-execution
is idempotent.

A side-effect of ``autocommit_block`` is that it COMMITs the
migration transaction, which releases the
``pg_advisory_xact_lock`` taken in ``alembic/env.py``.  In a fresh
rolling-deploy scenario where two ``alembic upgrade head`` processes
race, this opens a narrow window in which the second process can
observe ``alembic_version`` mid-upgrade and try to run the same
migration.  ``IF NOT EXISTS`` / ``DROP INDEX IF EXISTS`` cover the
idempotency for the index ops themselves; the swap-shadow ALTER
TYPE block above is *not* idempotent under that race.  Production
already has this migration at head, so the race window only
matters for fresh-DB initialisations (CI, dev, new prod).  Keep
``alembic upgrade head`` to a single-pod startup if you ever
re-bootstrap.

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
    # V5-E-2 — pure btree indexes built CONCURRENTLY so the analytics
    # tables stay write-available for the duration of the scan.  Each
    # index goes in its own autocommit-block because Postgres refuses
    # ``CREATE INDEX CONCURRENTLY`` inside a transaction.
    for name, table, cols in (
        ("ix_users_last_login_at", "users", ["last_login_at"]),
        ("ix_deals_completed_at", "deals", ["completed_at"]),
        ("ix_deals_arbitration_resolved_by", "deals", ["arbitration_resolved_by"]),
        ("ix_wallet_deposits_paid_at", "wallet_deposits", ["paid_at"]),
    ):
        with op.get_context().autocommit_block():
            op.create_index(
                name,
                table,
                cols,
                postgresql_concurrently=True,
                if_not_exists=True,
            )

    # ── L-10 ─────────────────────────────────────────────
    # ``deleted_at`` is nullable; ``NULL`` means "live". An index on
    # ``deleted_at`` is cheap and lets the list query use an index-only
    # filter; the server fills it in via ``utcnow()`` at delete time.
    op.add_column(
        "broadcasts",
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_broadcasts_deleted_at",
            "broadcasts",
            ["deleted_at"],
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_broadcasts_deleted_at",
            table_name="broadcasts",
            postgresql_concurrently=True,
            if_exists=True,
        )
    op.drop_column("broadcasts", "deleted_at")

    for name, table in (
        ("ix_wallet_deposits_paid_at", "wallet_deposits"),
        ("ix_deals_arbitration_resolved_by", "deals"),
        ("ix_deals_completed_at", "deals"),
        ("ix_users_last_login_at", "users"),
    ):
        with op.get_context().autocommit_block():
            op.drop_index(
                name,
                table_name=table,
                postgresql_concurrently=True,
                if_exists=True,
            )

    # Revert enum to pre-PR-H values. Any rows currently sitting on
    # ``refunded`` get coerced back to ``expired`` (the value they had
    # before the M-16 fix, so the downgrade matches the pre-PR-H
    # behaviour byte-for-byte).  This is the irreversible-data-loss
    # path documented in V5-E-1 at the top of the file.
    op.execute("UPDATE wallet_deposits SET status='expired' WHERE status='refunded'")
    op.execute("CREATE TYPE walletdepositstatus_new AS ENUM ('pending', 'paid', 'expired')")
    op.execute(
        "ALTER TABLE wallet_deposits "
        "ALTER COLUMN status TYPE walletdepositstatus_new "
        "USING status::text::walletdepositstatus_new"
    )
    op.execute("DROP TYPE walletdepositstatus")
    op.execute("ALTER TYPE walletdepositstatus_new RENAME TO walletdepositstatus")
