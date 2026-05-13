"""pr-3: service comments

Adds the ``service_comments`` table used by the Continental-style service
detail page. Each row is a public comment / mini-review left on a
``services`` row by another user. ``rating`` is optional (1-5) — comments
without a star rating are valid.

Revision ID: c3a7e1f24d12
Revises: 411cbe508b97
Create Date: 2026-05-13 18:30:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3a7e1f24d12"
down_revision: str | None = "411cbe508b97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "service_id",
            sa.Integer(),
            sa.ForeignKey("services.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_service_comments_service_id",
        "service_comments",
        ["service_id"],
    )
    op.create_index(
        "ix_service_comments_author_id",
        "service_comments",
        ["author_id"],
    )
    op.create_index(
        "ix_service_comments_created_at",
        "service_comments",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_service_comments_created_at", table_name="service_comments")
    op.drop_index("ix_service_comments_author_id", table_name="service_comments")
    op.drop_index("ix_service_comments_service_id", table_name="service_comments")
    op.drop_table("service_comments")
