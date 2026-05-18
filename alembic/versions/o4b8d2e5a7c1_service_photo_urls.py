"""service photo_urls gallery column

Adds ``services.photo_urls`` (``JSONB``, not-null, default ``'[]'``)
which stores a small ordered list of ``/media/...`` (or ``https://...``)
attachment URLs the owner can attach when creating / editing a service
via the V12-UI "Новая услуга" page. The list is capped at
``MAX_SERVICE_PHOTOS = 6`` entries by the Pydantic validators in
``backend/app/schemas.py`` so the catalogue endpoint stays cheap.

JSONB (not a relational ``service_photos`` table) is intentional:

* The gallery is always rendered with the owning row, never on its own,
  so we don't need an FK / index.
* The list is short (≤ 6 entries) and read-mostly.
* ``Service.photo_urls`` round-trips through SQLAlchemy as a plain
  ``list[str]`` thanks to the ``JSONB`` dialect adapter.

``server_default '[]'::jsonb`` is critical: it lets existing rows
auto-populate without a backfill, and means application code never
sees ``None`` (the column is also ``NOT NULL``).

Revision ID: o4b8d2e5a7c1
Revises: n3a7c9d2b8e5
Create Date: 2026-05-18 18:30:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "o4b8d2e5a7c1"
down_revision: str | None = "n3a7c9d2b8e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "services",
        sa.Column(
            "photo_urls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("services", "photo_urls")
