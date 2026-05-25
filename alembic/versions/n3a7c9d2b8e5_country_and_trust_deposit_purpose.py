"""country selector + trust deposit balance + wallet_deposits.purpose

Adds the three columns required for the
``profile-country-deposit-filter`` triplet:

* ``users.country`` (``String(2)``, nullable) — ISO-3166-1 alpha-2 code
  chosen by the user in profile settings. Surfaced on every public
  profile DTO; the canonical list of codes + flag emojis lives client-
  side in ``frontend/src/lib/countries.ts`` (no ``pycountry`` dep, no
  seed data).
* ``users.trust_deposit_balance`` (``Numeric(28, 8)``, default ``0``)
  — the new "deposit doverija" balance. Money credited here has *no*
  spend / withdraw path (lock-in by design); it only surfaces
  publicly as ``deposit`` on the user card.
* ``wallet_deposits.purpose`` (``String(16)``, default ``"wallet"``)
  — routing tag used by ``services_wallet.credit_deposit`` to branch
  between the existing ``UserBalance`` credit and the new
  ``User.trust_deposit_balance`` credit. Plain ``String`` (no Postgres
  enum) so a future third purpose doesn't need ``ALTER TYPE ADD VALUE``
  ceremony — the application layer enforces the closed set via the
  ``WalletDepositCreateReq.purpose`` ``Literal``.

Revision ID: n3a7c9d2b8e5
Revises: m1d8e3f7a2b4
Create Date: 2026-05-18 13:50:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "n3a7c9d2b8e5"
down_revision: str | None = "m1d8e3f7a2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "trust_deposit_balance",
                sa.Numeric(precision=28, scale=8),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "country",
                sa.String(length=2),
                nullable=True,
            )
        )
    with op.batch_alter_table("wallet_deposits") as batch:
        batch.add_column(
            sa.Column(
                "purpose",
                sa.String(length=16),
                nullable=False,
                server_default="wallet",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("wallet_deposits") as batch:
        batch.drop_column("purpose")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("country")
        batch.drop_column("trust_deposit_balance")
