"""p3.4: fts search_vector columns

Adds Postgres-generated ``tsvector`` columns on ``services`` and ``users``
plus GIN indexes used by the catalog and user-search endpoints. The
columns are ``GENERATED ALWAYS AS ... STORED`` so writes don't need
triggers; the source text fields are weighted via ``setweight``.

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
    op.create_index(
        "ix_services_search_vector",
        "services",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_users_search_vector",
        "users",
        ["search_vector"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_users_search_vector", table_name="users")
    op.drop_index("ix_services_search_vector", table_name="services")
    op.drop_column("users", "search_vector")
    op.drop_column("services", "search_vector")
