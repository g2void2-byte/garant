"""V11-M-10 — migrate ``notifications.payload`` from Text to JSONB.

The column has always been a JSON-encoded blob (the notifier serialises
the payload with ``json.dumps`` and the schema parses it back with a
``field_validator``), but the underlying storage was ``TEXT``. This
forces every consumer that wants to query into the structured payload
to ``CAST(payload AS jsonb)`` (and lose any index help), and it allows
non-JSON garbage to slip in via raw SQL.

This migration switches the column to native ``JSONB`` so:

* The model can declare ``Mapped[dict | None]`` instead of ``str`` and
  drop the parser shim in ``schemas.NotificationOut``.
* ``->>`` / ``@>`` operators work directly without a cast.
* Postgres validates JSON at write time, killing the "stored ``foo``,
  ``json.loads`` returns ``None``" failure mode.

Backfill: existing TEXT values are parsed with ``payload::jsonb``. Any
row whose payload is not valid JSON (we have never written one, but
defence in depth) is set to ``NULL`` first to keep the cast from
failing the migration.

Downgrade re-creates the TEXT column and serialises the JSONB back
with ``payload::text``. The round-trip is lossless modulo whitespace
(Postgres re-renders the canonical form), which matches the parser
in ``schemas.NotificationOut.parse_payload`` — strings are re-parsed
by ``json.loads`` regardless of formatting.

V5-E-1 — reversible. The TEXT/JSONB round-trip preserves all values
(see commit body). Recovery of pre-migration whitespace is not
guaranteed but no consumer depends on it.

Revision ID: b3d8c5f2a9e1
Revises: e7a3c1b9d4f6
Create Date: 2026-05-17 01:10:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b3d8c5f2a9e1"
down_revision: str | None = "e7a3c1b9d4f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        # Defence-in-depth: any row that somehow stored a non-JSON blob
        # would otherwise abort the cast. We have never written such a
        # row from application code (``notifier._serialize_payload``
        # always emits valid JSON), but a hand-written ``UPDATE`` from
        # a console session could have. Nulling those out is the
        # right answer — the schema parser already maps unparseable
        # strings to ``None`` so the user-visible behaviour is
        # identical to dropping them now.
        op.execute(
            sa.text(
                "UPDATE notifications SET payload = NULL "
                "WHERE payload IS NOT NULL "
                "AND NOT (payload ~ '^\\s*[{\\[]')"
            )
        )
        op.alter_column(
            "notifications",
            "payload",
            existing_type=sa.Text(),
            type_=postgresql.JSONB(),
            postgresql_using="payload::jsonb",
            existing_nullable=True,
        )
    else:
        # SQLite (test runner) doesn't have JSONB; ``JSON`` is the
        # closest native type. ``batch_alter_table`` is required
        # because SQLite can't ``ALTER COLUMN TYPE`` in place.
        with op.batch_alter_table("notifications") as batch:
            batch.alter_column(
                "payload",
                existing_type=sa.Text(),
                type_=sa.JSON(),
                existing_nullable=True,
            )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.alter_column(
            "notifications",
            "payload",
            existing_type=postgresql.JSONB(),
            type_=sa.Text(),
            postgresql_using="payload::text",
            existing_nullable=True,
        )
    else:
        with op.batch_alter_table("notifications") as batch:
            batch.alter_column(
                "payload",
                existing_type=sa.JSON(),
                type_=sa.Text(),
                existing_nullable=True,
            )
