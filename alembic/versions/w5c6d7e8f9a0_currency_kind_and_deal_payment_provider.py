"""currencies.kind + deals.payment_provider + fiat seed rows

User-facing plan items 1 and 6 split out into a single migration so
the schema and the seed data move in lockstep:

* ``currencies.kind`` (``String(8)``, default ``"crypto"``) — admin /
  service-layer hint distinguishing fiat invoices (UAH/RUB/USD) from
  crypto invoices (USDT/TON/...). The deposit page filters the
  dropdown by ``kind == 'fiat'`` so the user only sees fiat options
  while the back-end still understands crypto codes for historical
  rows and for the (future) provider-direct wallet flow. Plain
  ``String`` rather than a Postgres enum to avoid the
  ``ALTER TYPE ADD VALUE`` ceremony if a third kind ever lands.
* Fiat seed rows (``UAH``/``RUB``/``USD``) — created here rather than
  in :mod:`backend.app.seed` because the seeder only fires on a fresh
  install. Existing installs need the rows back-filled before the
  frontend dropdown has anything to show.
* ``deals.payment_provider`` (``String(16)``, default ``"cryptobot"``)
  — buyer's chosen invoice provider, captured at deal-create time
  so future invoice-driven escrow flows can route to the right
  upstream without re-asking the user. Plain ``String`` matches the
  ``WalletDepositCreateReq.provider`` ``Literal`` shape on the wallet
  side and keeps the closed set enforced in the pydantic layer.

The default values keep historical rows valid without a back-fill
pass — crypto currencies stay ``kind='crypto'`` and existing deals
default to ``payment_provider='cryptobot'`` (the only option before
this change).

Revision ID: w5c6d7e8f9a0
Revises: v4b5c6d7e8f9
Create Date: 2026-05-22 14:00:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "w5c6d7e8f9a0"
down_revision: str | None = "v4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Fiat rows back-filled by this migration. Mirror
# ``backend.app.seed.FIAT_CURRENCIES`` (the seeder applies the same
# set on fresh installs via ``ON CONFLICT DO NOTHING``).
# ``icon_url`` is NOT NULL on the ``currencies`` table (see the
# initial schema migration ``9d0e4d959e65``) — the model carries a
# python-side default of ``""`` but the column itself has no server
# default, so the back-fill INSERT has to provide a value explicitly
# or the seed crashes with ``NotNullViolationError``.
_FIAT_SEED: list[dict[str, object]] = [
    {
        "code": "USD",
        "name": "US Dollar",
        "network": "",
        "icon_url": "",
        "decimals": 2,
        "min_deposit": 1,
        "min_withdraw": 1,
        "sort_order": 200,
        "is_active": True,
        "address_regex": "",
        "kind": "fiat",
    },
    {
        "code": "UAH",
        "name": "Українська гривня",
        "network": "",
        "icon_url": "",
        "decimals": 2,
        "min_deposit": 50,
        "min_withdraw": 50,
        "sort_order": 210,
        "is_active": True,
        "address_regex": "",
        "kind": "fiat",
    },
    {
        "code": "RUB",
        "name": "Российский рубль",
        "network": "",
        "icon_url": "",
        "decimals": 2,
        "min_deposit": 100,
        "min_withdraw": 100,
        "sort_order": 220,
        "is_active": True,
        "address_regex": "",
        "kind": "fiat",
    },
]


def upgrade() -> None:
    with op.batch_alter_table("currencies") as batch:
        batch.add_column(
            sa.Column(
                "kind",
                sa.String(length=8),
                nullable=False,
                server_default="crypto",
            )
        )

    with op.batch_alter_table("deals") as batch:
        batch.add_column(
            sa.Column(
                "payment_provider",
                sa.String(length=16),
                nullable=False,
                server_default="cryptobot",
            )
        )

    # Back-fill fiat rows. ``ON CONFLICT (code) DO NOTHING`` keeps
    # the migration idempotent — a repeated run (or a clash with a
    # manually-inserted ``USD`` row from an older install) is a
    # no-op rather than a constraint-violation crash.
    currencies = sa.table(
        "currencies",
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("network", sa.String()),
        sa.column("icon_url", sa.Text()),
        sa.column("decimals", sa.Integer()),
        sa.column("min_deposit", sa.Numeric(28, 8)),
        sa.column("min_withdraw", sa.Numeric(28, 8)),
        sa.column("sort_order", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
        sa.column("address_regex", sa.Text()),
        sa.column("kind", sa.String()),
    )
    op.execute(
        sa.dialects.postgresql.insert(currencies)
        .values(_FIAT_SEED)
        .on_conflict_do_nothing(index_elements=["code"])
    )


def downgrade() -> None:
    # Delete only the fiat rows we own; an admin who later renamed
    # one of them or added their own ``USD`` row should keep their
    # data. Match by both ``code`` and ``kind='fiat'`` to avoid
    # touching a hypothetical legacy crypto ``USD`` row.
    op.execute("DELETE FROM currencies WHERE kind = 'fiat' AND code IN ('USD', 'UAH', 'RUB')")
    with op.batch_alter_table("deals") as batch:
        batch.drop_column("payment_provider")
    with op.batch_alter_table("currencies") as batch:
        batch.drop_column("kind")
