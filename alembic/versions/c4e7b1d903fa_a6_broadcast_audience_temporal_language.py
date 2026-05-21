"""A-6 — broadcast audience: temporal + language cohort filters

Extends the admin broadcast composer with three new cohort filters and
captures the Telegram client locale on the ``users`` row so the new
``audience_language`` filter has something to match against:

* ``users.language_code`` (``VARCHAR(16)``, NULLable, indexed) — the
  IETF language tag the Telegram client sent on first / last auth.
  Indexed because the broadcast audience query filters on exact-match
  values and the cardinality is bounded (Telegram normalises to a
  short set of two-/four-letter codes).
* ``broadcasts.audience_created_after`` (``TIMESTAMP``, NULLable) — only
  send to users with ``users.created_at >= this``.
* ``broadcasts.audience_created_before`` (``TIMESTAMP``, NULLable) —
  symmetric upper bound.
* ``broadcasts.audience_language`` (``VARCHAR(16)``, NULLable) —
  exact-match cohort (e.g. ``"ru"``).

All four columns are NULLable so the migration is a forward-compatible
add: existing rows look exactly like "filter not set" to the new
audience builder.

Revision ID: c4e7b1d903fa
Revises: b3d8c5f2a9e1
Create Date: 2026-05-17 11:20:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4e7b1d903fa"
down_revision: str | None = "b3d8c5f2a9e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Audit §15.9 — ``add_column`` of a NULLable column without a
    # default is a *metadata-only* change in Postgres (no table rewrite,
    # no full ACCESS EXCLUSIVE on the data pages). That's why it's safe
    # to follow up with ``CREATE INDEX CONCURRENTLY`` on the same
    # ``users`` table in the same migration: the prior add_column does
    # not hold a long-lived exclusive lock, and the autocommit_block
    # below explicitly drops the transaction so the concurrent build
    # runs against a hot table without serialising writers.
    op.add_column(
        "users",
        sa.Column("language_code", sa.String(length=16), nullable=True),
    )
    # Index lookup is on exact equality (``users.language_code = :lang``),
    # so a regular btree is plenty — no need for ``lower(...)``
    # functional index, ``deps._normalise_language_code`` stores the
    # value already lowercased.
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_users_language_code",
            "users",
            ["language_code"],
            unique=False,
            if_not_exists=True,
            postgresql_concurrently=True,
        )

    op.add_column(
        "broadcasts",
        sa.Column("audience_created_after", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "broadcasts",
        sa.Column("audience_created_before", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "broadcasts",
        sa.Column("audience_language", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("broadcasts") as batch:
        batch.drop_column("audience_language")
        batch.drop_column("audience_created_before")
        batch.drop_column("audience_created_after")

    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_users_language_code",
            table_name="users",
            if_exists=True,
            postgresql_concurrently=True,
        )
    with op.batch_alter_table("users") as batch:
        batch.drop_column("language_code")
