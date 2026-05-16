"""Comment 33: FK CASCADE on service_comments + SET NULL on reviews.

Add ``ondelete="CASCADE"`` to ``service_comments.service_id`` so
deleting a service automatically removes its comments (instead of
leaving orphan rows that cause FK violations on queries).

Add ``ondelete="SET NULL"`` to ``reviews.deal_id`` so deleting a deal
nulls the back-reference instead of blocking with an FK constraint
error.

Revision ID: a1b2c3d4e5f6
Revises: d9f1c3a8e205
Create Date: 2026-05-16 19:00:00.000000
"""

from __future__ import annotations

from typing import Sequence

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "d9f1c3a8e205"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # service_comments.service_id → CASCADE
    op.drop_constraint(
        "service_comments_service_id_fkey",
        "service_comments",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "service_comments_service_id_fkey",
        "service_comments",
        "services",
        ["service_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # reviews.deal_id → SET NULL
    op.drop_constraint(
        "reviews_deal_id_fkey",
        "reviews",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "reviews_deal_id_fkey",
        "reviews",
        "deals",
        ["deal_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "reviews_deal_id_fkey",
        "reviews",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "reviews_deal_id_fkey",
        "reviews",
        "deals",
        ["deal_id"],
        ["id"],
    )

    op.drop_constraint(
        "service_comments_service_id_fkey",
        "service_comments",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "service_comments_service_id_fkey",
        "service_comments",
        "services",
        ["service_id"],
        ["id"],
    )
