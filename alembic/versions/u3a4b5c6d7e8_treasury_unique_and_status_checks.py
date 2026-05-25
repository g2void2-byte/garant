"""Audit §15.3 / §15.4 — treasury unique + status CHECK constraints

Two follow-up invariants on top of the ``a1c4f8e2b5d7`` schema:

* **§15.3** — partial UNIQUE INDEX on
  ``treasury_withdrawals.cryptobot_transfer_id`` (``WHERE … IS NOT NULL``).
  The column is the natural idempotency key for outbound CryptoBot
  transfers (``services_treasury.execute_phase3`` reads it back to
  recover from a crashed Phase 3 commit). Without the unique index the
  invariant lives only in application code; a future regression
  (botched retry loop, replay of a webhook, schema-direct INSERT from
  ops) could land two ``treasury_withdrawals`` rows pointing at the
  same external transfer. Partial because rows in the ``pending``
  state legitimately have ``NULL`` here until Phase 3 records the
  transfer id.

* **§15.4** — CHECK constraints pinning the closed value set on
  ``treasury_withdrawals.status`` and ``broadcasts.status``. Both
  columns are bare ``String(16)`` (chosen over Postgres ENUMs in the
  parent migration so adding a new state stays a one-line schema
  change) and were enforced only via the FastAPI ``Literal`` types.
  These CHECKs act as defence-in-depth so a direct SQL write cannot
  land a row the API would otherwise reject.

  * ``treasury_withdrawals.status`` — ``{'pending', 'sent', 'failed',
    'rejected'}``. The first three are the values actually set by
    ``services_treasury`` / ``treasury_mark_sent``; ``rejected`` is
    listed in the model docstring as a planned terminal state and
    kept here to avoid a no-op migration the moment that lands.
  * ``broadcasts.status`` — ``{'draft', 'sent'}``. Matches the model
    docstring (``draft`` when ``scheduled_at`` is set, ``sent`` once
    dispatched).

Both CHECKs validate existing rows on apply; if a legacy row would
fail, the migration refuses to land and the operator must clean the
data first. This is intentional — silently coercing user-supplied
data during a migration would lose the offending value.

Revision ID: u3a4b5c6d7e8
Revises: t2b3c4d5e6f7
Create Date: 2026-05-22 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "u3a4b5c6d7e8"
down_revision: str | None = "t2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # §15.3 — partial UNIQUE INDEX. ``CREATE INDEX CONCURRENTLY`` would
    # be safer on a hot table, but ``treasury_withdrawals`` is a small
    # write-rare ledger (an admin clicks "withdraw" by hand) so a
    # synchronous build is fine and keeps the migration transactional.
    op.create_index(
        "uq_treasury_withdrawals_cryptobot_transfer_id",
        "treasury_withdrawals",
        ["cryptobot_transfer_id"],
        unique=True,
        postgresql_where=sa.text("cryptobot_transfer_id IS NOT NULL"),
    )
    # §15.4 — CHECK constraints on the two free-form status columns.
    op.create_check_constraint(
        "ck_treasury_withdrawals_status_known",
        "treasury_withdrawals",
        "status IN ('pending', 'sent', 'failed', 'rejected')",
    )
    op.create_check_constraint(
        "ck_broadcasts_status_known",
        "broadcasts",
        "status IN ('draft', 'sent')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_broadcasts_status_known", "broadcasts", type_="check")
    op.drop_constraint(
        "ck_treasury_withdrawals_status_known", "treasury_withdrawals", type_="check"
    )
    op.drop_index(
        "uq_treasury_withdrawals_cryptobot_transfer_id",
        table_name="treasury_withdrawals",
    )
