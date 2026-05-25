"""Drop dead-stub columns and harden review/comment FK cascades

Audit follow-up. Three independent schema changes batched into one
revision because they are all the same shape (DDL on existing tables
with no data migration) and each carries the same destructive
downgrade risk.

V5-E-1 — irreversible data loss on downgrade

Columns removed (the data does not survive a downgrade):

* ``account_transfer_codes.attempts`` — dead-stub counter. The
  endpoint-level rate-limiter (``RLPin`` 5 req/min/caller) plus the
  6-digit/15-min OTP keyspace already win the brute-force math; the
  per-code counter only ever bumped on cosmic-ray-rare hash
  collisions and the rest of the codebase treated it as a no-op.
* ``wallet_withdrawals.locked_until`` — dead-stub cooldown. The
  "dispute window" enforcement was never wired (neither
  ``decide_withdrawal`` nor auto-mode ``create_withdrawal`` consulted
  the value, and there was no user-facing cancel endpoint to consume
  it). The frontend surfaced the timestamp as "funds locked until X"
  even though they were already either spent or refunded — that UX
  lie is now removed alongside the column.
* ``deals.arbitrage_reason`` — legacy mirror of
  ``deals.arbitration_reason``. No reader exists in backend, admin
  UI, frontend, or bot; the write was kept "just in case" for an
  out-of-process consumer that never materialised.

FK ``ondelete`` policies added so a ``DELETE FROM users WHERE id=X``
no longer trips a constraint violation:

* ``service_comments.author_id`` → ``CASCADE`` (author's comments
  go with the author).
* ``reviews.author_id`` → ``CASCADE`` (author's reviews go with the
  author).
* ``reviews.target_id`` → ``CASCADE`` (reviews about a user go with
  that user).

Revision ID: r9a3b6c2d8e1
Revises: q7d8e2c1f4a9
Create Date: 2026-05-19 16:00:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "r9a3b6c2d8e1"
down_revision: str | None = "q7d8e2c1f4a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. Drop stub columns ────────────────────────────────
    op.drop_column("account_transfer_codes", "attempts")
    op.drop_column("wallet_withdrawals", "locked_until")
    op.drop_column("deals", "arbitrage_reason")

    # ── 2. Harden FKs on service_comments + reviews ─────────
    # ``service_comments.author_id`` → CASCADE
    op.drop_constraint(
        "service_comments_author_id_fkey",
        "service_comments",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "service_comments_author_id_fkey",
        "service_comments",
        "users",
        ["author_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ``reviews.author_id`` → CASCADE
    op.drop_constraint(
        "reviews_author_id_fkey",
        "reviews",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "reviews_author_id_fkey",
        "reviews",
        "users",
        ["author_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ``reviews.target_id`` → CASCADE
    op.drop_constraint(
        "reviews_target_id_fkey",
        "reviews",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "reviews_target_id_fkey",
        "reviews",
        "users",
        ["target_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # ── 1. FK policies revert to default (no ondelete) ──────
    op.drop_constraint(
        "reviews_target_id_fkey",
        "reviews",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "reviews_target_id_fkey",
        "reviews",
        "users",
        ["target_id"],
        ["id"],
    )

    op.drop_constraint(
        "reviews_author_id_fkey",
        "reviews",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "reviews_author_id_fkey",
        "reviews",
        "users",
        ["author_id"],
        ["id"],
    )

    op.drop_constraint(
        "service_comments_author_id_fkey",
        "service_comments",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "service_comments_author_id_fkey",
        "service_comments",
        "users",
        ["author_id"],
        ["id"],
    )

    # ── 2. Re-add the stub columns as nullable ──────────────
    # Data does NOT survive the downgrade — the upgrade dropped it.
    # Nullable so the round-trip is clean even though the matching
    # application code on this revision wrote values on every insert.
    op.add_column(
        "deals",
        sa.Column("arbitrage_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "wallet_withdrawals",
        sa.Column("locked_until", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "account_transfer_codes",
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
