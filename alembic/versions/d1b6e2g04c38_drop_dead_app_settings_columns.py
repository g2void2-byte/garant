"""Drop dead/inert ``app_settings`` columns.

Static-analysis audit of every ``app_settings`` column edited by
``PATCH /api/admin/settings`` (see ``docs/audit/admin-settings-audit.md``
proposed in PR #230) flagged three columns as either unused or
silently inert:

* ``invoice_commission_percent`` — **DEAD CODE.** No consumer in
  ``backend/app/services_*.py``, ``backend/app/routers/*.py``,
  ``cryptopay.py``, the bot, or anywhere else. The admin form
  persisted edits, the audit log recorded the diff, but no business
  code multiplied any amount by it. An operator setting a non-zero
  value here would silently get no platform fees on invoices.

* ``min_deposit`` (singleton) — **INERT.** Wallet deposits enforce
  the per-currency override at ``Currency.min_deposit`` (see
  ``services_wallet.create_deposit_invoice``); the singleton value
  was read only by the admin settings router to populate the form
  payload. The model docstring on the column itself acknowledged
  this ("global default kept around for admin display"), but the
  admin form did not — setting the value to 100 still let users
  deposit 1 USDT.

* ``min_withdraw`` (singleton) — **INERT.** Same pattern. Wallet
  withdrawals enforce ``Currency.min_withdraw``; the singleton was
  display-only.

Dropping all three is mechanical because none of them drove
behaviour. The per-currency overrides at ``Currency.min_deposit`` /
``Currency.min_withdraw`` (which are the actual enforcement points)
are untouched by this migration.

V5-E-1 — irreversible data loss on downgrade
--------------------------------------------
The downgrade re-adds the columns with their original defaults
(``invoice_commission_percent=0.0``, ``min_deposit=1.0``,
``min_withdraw=1.0``) so the schema shape matches. Per-row historical
values (if any operator did set them via the form pre-cutover) are
lost — they could not have driven behaviour anyway, so there is
nothing to recover.

Revision ID: d1b6e2g04c38
Revises: c0a5e1f93b27
Create Date: 2026-05-23 22:40:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1b6e2g04c38"
down_revision: str | None = "c0a5e1f93b27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("app_settings") as batch:
        batch.drop_column("invoice_commission_percent")
        batch.drop_column("min_deposit")
        batch.drop_column("min_withdraw")


def downgrade() -> None:
    # V5-E-1: restores the column shape with the seed-time defaults
    # (``invoice_commission_percent=0.0``, ``min_deposit=1.0``,
    # ``min_withdraw=1.0`` per ``backend/app/seed.py:115-120``
    # before this revision). The widened ``Numeric(28, 8)``
    # precision on the min columns matches the H-2 widening
    # migration. The columns were ``NOT NULL`` with server defaults
    # in the live schema, so we restore that shape exactly.
    with op.batch_alter_table("app_settings") as batch:
        batch.add_column(
            sa.Column(
                "invoice_commission_percent",
                sa.Numeric(precision=5, scale=2),
                nullable=False,
                server_default="0.0",
            ),
        )
        batch.add_column(
            sa.Column(
                "min_deposit",
                sa.Numeric(precision=28, scale=8),
                nullable=False,
                server_default="1",
            ),
        )
        batch.add_column(
            sa.Column(
                "min_withdraw",
                sa.Numeric(precision=28, scale=8),
                nullable=False,
                server_default="1",
            ),
        )
