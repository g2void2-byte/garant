"""H-1 — retire legacy User.balance / Invoice ledger.

Revision ID: h1a2b3c4d5e6
Revises: 9c3a4d2e1f08
Create Date: 2026-05-17 19:30:00.000000

Irreversible: yes

V12-I11 — contract reminders:

V5-E-1 — irreversible data loss on downgrade

The pre-multi-currency platform tracked deposits in two ways:

* a single ``users.balance`` ``Numeric(14,2)`` USD column credited
  by the legacy ``services.credit_invoice`` helper, and
* an ``invoices`` table holding each ``(provider, provider_invoice_id,
  amount, status)`` row issued through the legacy
  ``POST /api/payments/deposit*`` endpoints.

H-1 retires both. New deposits flow through ``WalletDeposit`` /
``UserBalance(currency_id, amount, locked)`` only. This migration
performs the one-shot data merge:

1. Backfill ``users.balance > 0`` into ``user_balances`` under the
   ``USDT`` currency row, summing any pre-existing ``UserBalance``
   row with the same ``(user_id, USDT)`` key (the unique constraint
   added by ``e7a3c1b9d4f6`` makes the upsert deterministic).
2. Backfill ``deals.currency_id IS NULL`` rows to ``USDT`` so the
   wallet-only ``services_deals`` code path can treat every deal
   uniformly. Pre-multi-currency deals were stored on the legacy
   USD ``Deal.sum`` column with no ``currency_id``; H-1 folds them
   into USDT to match the legacy USD semantic.
3. Write one ``admin_audit_log`` row per affected user before the
   data merge so the operator has a permanent ledger of what was
   moved and from what value.
4. Drop ``users.balance``.
5. Drop the ``invoices`` table.
6. Drop the ``invoicestatus`` enum type.
7. Rename the ``invoiceprovider`` enum type to
   ``walletdepositprovider`` so the surviving ``WalletDeposit.provider``
   column keeps a stable Python enum mapping (the column already
   uses the enum's storage; renaming the type avoids a destructive
   drop+recreate that would force a column rewrite).

Pre-flight notes (from the H-1 audit §5):

* This migration assumes a ``currencies`` row with ``code='USDT'``
  exists. The seed creates it in every environment; the migration
  fails loudly with ``RuntimeError`` if it is missing rather than
  silently skipping the backfill.
* Production may still hold ``invoices.status='pending'`` rows at the
  moment the migration runs. The H-1 deploy plan is to drain that
  set to zero (wait out the CryptoBot expiry window) before applying
  this migration so a late ``invoice_paid`` webhook for a row that no
  longer exists fails cleanly with ``unknown invoice``.

Downgrade is intentionally not implemented — once ``users.balance``
is dropped and the legacy ``invoices`` table is gone, restoring the
pre-H-1 state requires the operator to roll back to a database
snapshot taken before the migration. The matching contract test
``tests/test_v5_d_e_bucket.py::test_destructive_migrations_document_irreversible_data_loss``
grep-matches the marker above and will fail if it is removed.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "h1a2b3c4d5e6"
down_revision: Union[str, None] = "9c3a4d2e1f08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- pre-flight: USDT currency must exist ------------------------------
    usdt_id = bind.execute(
        sa.text("SELECT id FROM currencies WHERE code = 'USDT' LIMIT 1")
    ).scalar()

    needs_balance_backfill = bool(
        bind.execute(
            sa.text("SELECT EXISTS(SELECT 1 FROM users WHERE balance IS NOT NULL AND balance > 0)")
        ).scalar()
    )
    needs_currency_backfill = bool(
        bind.execute(
            sa.text("SELECT EXISTS(SELECT 1 FROM deals WHERE currency_id IS NULL)")
        ).scalar()
    )

    if (needs_balance_backfill or needs_currency_backfill) and usdt_id is None:
        raise RuntimeError(
            "H-1 migration requires a 'USDT' row in the 'currencies' table to "
            "backfill legacy User.balance / null currency_id deals. Seed the row "
            "(see backend.app.seed) before running this migration."
        )

    # --- step 1: per-user audit row BEFORE the balance merge ---------------
    # Audit row payload mirrors :func:`backend.app.admin_audit.state_change_payload`
    # so downstream tooling can pivot on the same shape as application-emitted
    # admin actions. ``actor_id`` is NULL because the system (this migration)
    # is the actor, not a real admin user.
    if needs_balance_backfill:
        bind.execute(
            sa.text(
                """
                INSERT INTO admin_audit_log
                    (actor_id, action, target_type, target_id, reason, payload, ip, created_at)
                SELECT
                    NULL,
                    'h1.legacy_balance_backfilled',
                    'user',
                    u.id,
                    NULL,
                    jsonb_build_object(
                        'before', jsonb_build_object('balance_usd', u.balance::text),
                        'after', jsonb_build_object('currency', 'USDT', 'amount', u.balance::text),
                        'diff', jsonb_build_object('amount', u.balance::text),
                        'context', jsonb_build_object('migration', 'h1a2b3c4d5e6')
                    ),
                    NULL,
                    NOW()
                FROM users u
                WHERE u.balance IS NOT NULL AND u.balance > 0
                """
            )
        )

    # --- step 2: balance backfill, USDT currency, sum into existing row ---
    if needs_balance_backfill:
        bind.execute(
            sa.text(
                """
                INSERT INTO user_balances (user_id, currency_id, amount, locked, updated_at)
                SELECT u.id, :usdt_id, u.balance, 0, NOW()
                FROM users u
                WHERE u.balance IS NOT NULL AND u.balance > 0
                ON CONFLICT (user_id, currency_id) DO UPDATE
                    SET amount = user_balances.amount + EXCLUDED.amount,
                        updated_at = NOW()
                """
            ),
            {"usdt_id": usdt_id},
        )

    # --- step 3: deal currency_id backfill -------------------------------
    if needs_currency_backfill:
        bind.execute(
            sa.text("UPDATE deals SET currency_id = :usdt_id WHERE currency_id IS NULL"),
            {"usdt_id": usdt_id},
        )

    # --- step 4: drop users.balance --------------------------------------
    op.drop_column("users", "balance")

    # --- step 5: drop invoices table -------------------------------------
    op.drop_table("invoices")

    # --- step 6: drop invoicestatus enum type ----------------------------
    # ``DROP TYPE`` is fine after the table is gone; no other column
    # references this enum.
    op.execute("DROP TYPE IF EXISTS invoicestatus")

    # --- step 7: rename invoiceprovider -> walletdepositprovider ---------
    # ``WalletDeposit.provider`` already stores values in the
    # ``invoiceprovider`` enum type (the original models.py had it
    # share the InvoiceProvider Python enum, which generated a single
    # DB type the first migration ran ``CREATE TYPE`` on). Renaming
    # is a pure metadata operation — no column rewrite, the existing
    # values stay the same — so we can rename in place rather than
    # creating a new type and rewriting ``wallet_deposits``.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'invoiceprovider')
               AND NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'walletdepositprovider')
            THEN
                ALTER TYPE invoiceprovider RENAME TO walletdepositprovider;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    # H-1 is intentionally one-way. ``users.balance`` has been dropped,
    # the ``invoices`` table is gone, and the ``invoiceprovider`` enum
    # type has been renamed. Restoring the pre-H-1 state requires
    # rolling back the database from a snapshot taken before the
    # migration ran; there is no in-place reverse path that
    # reconstructs the legacy USD ledger from the merged
    # ``user_balances(USDT)`` rows without losing the per-row
    # ``Invoice.provider_invoice_id`` / ``status`` history.
    raise RuntimeError(
        "H-1 (h1a2b3c4d5e6) is irreversible. Restore the database from a "
        "pre-H-1 snapshot to roll back."
    )
