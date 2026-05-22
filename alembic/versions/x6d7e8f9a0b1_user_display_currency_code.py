"""users.display_currency_code

Adds ``users.display_currency_code`` (``String(8)``, nullable) — the
fiat currency code the user picked in ``/profile/settings`` as the
"main" balance shown on the new ``ProfilePage`` fiat-balance card.

``None`` is the canonical "not picked yet" sentinel; the UI falls
back to ``USD`` in that case so existing users see something
sensible before they hit the settings page. The column is left
nullable rather than defaulted to ``"USD"`` on the server side so a
fresh row can be distinguished from one the user explicitly chose
USD on — handy for the upcoming first-login analytics hook (out of
scope here, no telemetry shipped in this revision).

The column is a plain ``String(8)`` rather than a foreign key to
``currencies.code`` so that an admin deactivating a fiat currency
doesn't strand the column with a dangling reference: the user's
preference stays valid until they pick a different code via PATCH
``/api/me``, and the back-end falls back to ``USD`` when serialising
a deactivated / unknown code. Nine bytes covers every active fiat
code in :data:`backend.app.seed.FIAT_CURRENCIES` (the longest is
three characters today) with comfortable head-room.

Revision ID: x6d7e8f9a0b1
Revises: w5c6d7e8f9a0
Create Date: 2026-05-22 17:30:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "x6d7e8f9a0b1"
down_revision: str | None = "w5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "display_currency_code",
                sa.String(length=8),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("display_currency_code")
