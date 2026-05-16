"""p3.4: fts search_vector columns

Adds Postgres-generated ``tsvector`` columns on ``services`` and ``users``
plus GIN indexes used by the catalog and user-search endpoints. The
columns are ``GENERATED ALWAYS AS ... STORED`` so writes don't need
triggers; the source text fields are weighted via ``setweight``.

V5-E-3 — ``CREATE INDEX CONCURRENTLY`` for FTS
----------------------------------------------
The GIN indexes on the ``search_vector`` columns are the most
expensive index builds in the schema: GIN scans every existing row,
tokenises each ``tsvector``, and materialises the posting list. On
the ``services`` / ``users`` tables (the two largest text-bearing
tables in the system) that's many seconds of ``ACCESS EXCLUSIVE``
under the plain ``CREATE INDEX`` form — which blocks every
concurrent write on the catalog / profile endpoints for the
duration of the build.

Each ``op.create_index`` is wrapped in
:func:`alembic.runtime.migration.MigrationContext.autocommit_block`
so it runs ``CREATE INDEX CONCURRENTLY`` (``SHARE UPDATE EXCLUSIVE``
lock only — concurrent reads + writes allowed).  ``if_not_exists`` /
``if_exists`` keep the migration idempotent under retries.

Side-effect of ``autocommit_block``: see the matching note in
``c8f4a2e91d35`` — it commits the migration transaction, releasing
the ``pg_advisory_xact_lock`` from ``alembic/env.py``.  The
``ADD COLUMN ... GENERATED ALWAYS AS ... STORED`` step above is
itself table-rewriting and *not* idempotent, so just like the L-9
indexes, this migration is only safe to run concurrently on a
fresh DB if you can guarantee single-pod bootstrap.  Production is
already at head so the race window only matters for new DBs.

Revision ID: b8adfad43818
Revises: 9d0e4d959e65
Create Date: 2026-05-13 16:56:23.694728
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b8adfad43818"
down_revision: str | None = "9d0e4d959e65"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SERVICES_VECTOR_EXPR = (
    "setweight(to_tsvector('simple', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('simple', coalesce(description, '')), 'B')"
)
_USERS_VECTOR_EXPR = (
    "setweight(to_tsvector('simple', coalesce(username, '')), 'A') || "
    "setweight(to_tsvector('simple', coalesce(display_name, '')), 'B') || "
    "setweight(to_tsvector('simple', coalesce(description, '')), 'C')"
)


def upgrade() -> None:
    op.add_column(
        "services",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(_SERVICES_VECTOR_EXPR, persisted=True),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(_USERS_VECTOR_EXPR, persisted=True),
            nullable=True,
        ),
    )
    # V5-E-3 — GIN indexes are the most expensive build in the schema;
    # CONCURRENTLY swaps the table-blocking ``ACCESS EXCLUSIVE`` for
    # ``SHARE UPDATE EXCLUSIVE`` so reads and writes keep flowing
    # during the scan.  Each index goes in its own autocommit-block
    # because Postgres refuses ``CREATE INDEX CONCURRENTLY`` inside a
    # transaction.
    for name, table in (
        ("ix_services_search_vector", "services"),
        ("ix_users_search_vector", "users"),
    ):
        with op.get_context().autocommit_block():
            op.create_index(
                name,
                table,
                ["search_vector"],
                postgresql_using="gin",
                postgresql_concurrently=True,
                if_not_exists=True,
            )


def downgrade() -> None:
    for name, table in (
        ("ix_users_search_vector", "users"),
        ("ix_services_search_vector", "services"),
    ):
        with op.get_context().autocommit_block():
            op.drop_index(
                name,
                table_name=table,
                postgresql_concurrently=True,
                if_exists=True,
            )
    op.drop_column("users", "search_vector")
    op.drop_column("services", "search_vector")
