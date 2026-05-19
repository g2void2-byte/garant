"""Add ``crystalpay`` to the ``walletdepositprovider`` enum

A new payment provider (Crystalpay v3) is wired alongside CryptoBot
for wallet top-ups. ``WalletDeposit.provider`` already stores the
provider tag via a Postgres ``ENUM`` named ``walletdepositprovider``
(see ``backend.app.models.WalletDepositProvider``), so we extend the
enum with the new value.

Postgres allows ``ALTER TYPE ... ADD VALUE`` inside a transaction
block since 12.0, so this stays single-statement. ``IF NOT EXISTS``
keeps it idempotent — re-running the migration (e.g. via the alembic
advisory-lock retry path in
``backend.app.db._upgrade_to_head_sync``) is a no-op rather than a
duplicate-value error.

Postgres has no ``ALTER TYPE ... DROP VALUE`` so the downgrade is a
no-op: rolling back the application code without rolling back the
enum value is safe (the extra value just stops being referenced),
and forcing a destructive shadow-type rebuild on downgrade would be
disproportionate to the actual risk.

Revision ID: q7d8e2c1f4a9
Revises: p5c9e3f1b8d7
Create Date: 2026-05-19 09:00:00.000000
"""

from __future__ import annotations

from typing import Sequence

from alembic import op

revision: str = "q7d8e2c1f4a9"
down_revision: str | None = "p5c9e3f1b8d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE walletdepositprovider ADD VALUE IF NOT EXISTS 'crystalpay'")


def downgrade() -> None:
    # Postgres has no ``ALTER TYPE ... DROP VALUE``. Leaving the
    # value in place is harmless: application code on the prior
    # revision simply never writes it, and any historical row that
    # already carries it would be a data-only concern, not a schema
    # one. A destructive shadow-type rebuild would be
    # disproportionate to that risk.
    pass
