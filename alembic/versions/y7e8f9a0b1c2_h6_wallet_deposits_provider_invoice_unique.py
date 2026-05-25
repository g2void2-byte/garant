"""wallet_deposits: unique (provider, provider_invoice_id)

Audit H-6 — pre-fix ``wallet_deposits.provider_invoice_id`` was only
*indexed* (not unique), so a Crystalpay invoice with ``id=42`` could
coexist with a CryptoBot invoice carrying ``invoice_id=42``. The
webhook dispatch in ``services_payments._find_wallet_deposit`` keyed
its lookup solely on ``provider_invoice_id`` — meaning a Crystalpay
delivery could load a CryptoBot row (or vice versa) and either:

* credit the wrong user's balance,
* flip the wrong row to ``expired``,
* silently no-op (depending on which row ``scalar_one_or_none``
  returned).

The fix is two-pronged. In code, ``_find_wallet_deposit`` now
requires a ``provider=WalletDepositProvider`` argument and includes
it in the ``WHERE`` clause. At the schema level, a composite UNIQUE
index on ``(provider, provider_invoice_id)`` makes the per-provider
namespace explicit: any future code path that forgets the
``provider`` filter would either return zero rows (good) or trip the
unique constraint at INSERT time (also good — we'd notice
immediately).

The plain ``provider_invoice_id`` index is retained because admin
support tools occasionally pivot on the raw upstream id when the
provider is unknown (rare — used by the "find by webhook id"
shortcut in the back-office). The retained index is non-unique by
intent.

Revision ID: y7e8f9a0b1c2
Revises: x6d7e8f9a0b1
Create Date: 2026-05-22 23:55:00.000000
"""

from __future__ import annotations

from typing import Sequence

from alembic import op

revision: str = "y7e8f9a0b1c2"
down_revision: str | None = "x6d7e8f9a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ``unique=True`` here is what closes the H-6 race. The existing
    # non-unique ``ix_wallet_deposits_provider_invoice_id`` index is
    # kept (no DROP below) so the rare ``WHERE provider_invoice_id =
    # ?`` lookups in the admin back-office still hit an index.
    op.create_index(
        "ux_wallet_deposits_provider_provider_invoice_id",
        "wallet_deposits",
        ["provider", "provider_invoice_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ux_wallet_deposits_provider_provider_invoice_id",
        table_name="wallet_deposits",
    )
