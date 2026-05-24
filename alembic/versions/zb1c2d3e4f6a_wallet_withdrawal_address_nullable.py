"""Make WalletWithdrawal.address nullable for CryptoBot Transfer payouts.

When ``app_settings.auto_withdraw_enabled`` is on and a real
``CRYPTOBOT_TOKEN`` is configured, the user-facing withdrawal flow
identifies the recipient by ``users.tg_user_id`` (CryptoBot's
``transfer`` API) rather than an on-chain address. The legacy
``address`` field is irrelevant in that mode and the frontend stops
collecting it — so the column has to accept ``NULL`` for new rows.

Historical rows are left untouched (no data migration). The model and
schema treat ``address`` as ``str | None`` everywhere.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "zb1c2d3e4f6a"
down_revision: Union[str, None] = "a16d9c908a5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("wallet_withdrawals") as batch:
        batch.alter_column(
            "address",
            existing_type=sa.String(length=256),
            nullable=True,
        )


def downgrade() -> None:
    # Rows created with ``address IS NULL`` after the upgrade cannot be
    # rolled back to a non-null column without losing information. We
    # back-fill with an empty string so the constraint reapplies, but
    # the original "address absent" signal is irrecoverable.
    op.execute("UPDATE wallet_withdrawals SET address = '' WHERE address IS NULL")
    with op.batch_alter_table("wallet_withdrawals") as batch:
        batch.alter_column(
            "address",
            existing_type=sa.String(length=256),
            nullable=False,
        )
