"""notification_dlq table for dropped oversize notification payloads

Audit v3 A-2 — Pre-fix ``_payload_within_cap`` in ``notifier.py``
dropped oversize payloads with a ``logger.warning`` and the parent
``Notification`` row was inserted without the payload column.  The
dropped data was effectively lost; only the log line carried the
keys/byte count and the SRE could not join it back to the recipient
timeline in a database query.

This migration adds a ``notification_dlq`` table that the notifier
fills whenever it drops a payload at the cap.  The row carries the
metadata (encoded length, top-level keys) plus a bounded excerpt of
the JSON encoding for forensic recovery.

Revision ID: a9b1c2d3e4f5
Revises: z8f9a0b1c2d3
Create Date: 2026-05-23 18:00:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a9b1c2d3e4f5"
down_revision: str | None = "z8f9a0b1c2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_dlq",
        sa.Column("id", sa.Integer(), primary_key=True),
        # ``ON DELETE SET NULL`` so a recipient-driven purge of the
        # parent notifications row doesn't cascade away the DLQ
        # entry — keeping the metadata after the row is gone is the
        # whole point.
        sa.Column(
            "notification_id",
            sa.Integer(),
            sa.ForeignKey("notifications.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        # Recipient denormalised so "show all dropped payloads for
        # user X" stays a single indexed scan even after the parent
        # row is gone.
        sa.Column(
            "recipient_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("encoded_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_keys", postgresql.JSONB(), nullable=True),
        sa.Column("payload_excerpt", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("notification_dlq")
