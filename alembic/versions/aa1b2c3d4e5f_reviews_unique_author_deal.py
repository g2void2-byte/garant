"""reviews: UNIQUE (author_id, deal_id)

Code review §1.1 — pre-fix ``post_review`` validated "no existing
review from this author for this deal" via a check-then-act SELECT
followed by an INSERT. Two parallel ``POST /api/reviews`` calls from
the same author for the same deal could both see ``existing is
None`` and both succeed, doubling the target's ``good`` / ``bad``
counters (the post-INSERT ``recompute_user_rating`` pass counts both
rows). The DB had only the non-unique ``ix_reviews_author_id`` /
``ix_reviews_target_id`` indexes — no schema-level guard.

The fix is two-pronged. ``post_review`` (and the admin
``review.create`` path) now wrap the flush in ``except IntegrityError
→ 409``, and at the schema level a UNIQUE constraint on
``(author_id, deal_id)`` makes the racing INSERT abort at the
database. PostgreSQL treats NULLs as distinct in UNIQUE constraints,
so the historical ``deal_id IS NULL`` rows produced by the
``deals.ondelete=SET NULL`` cascade never collide with each other —
the constraint only binds rows where both columns are NOT NULL.

Pre-create cleanup: any pre-existing duplicates from racing requests
are deduped by keeping the lowest ``id`` per ``(author_id, deal_id)``
group (the chronologically-first INSERT — the second one's
``recompute_user_rating`` was the one that double-counted). After
deletion the affected ``users.good`` / ``users.bad`` counters are
recomputed from the surviving rows so the post-migration projection
matches the table.

Revision ID: aa1b2c3d4e5f
Revises: d1b6e2g04c38
Create Date: 2026-05-24 10:00:00.000000
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "aa1b2c3d4e5f"
down_revision: str | None = "d1b6e2g04c38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # Step 1 — capture the set of target users whose ``good`` / ``bad``
    # counters will move after dedup so we only recompute the ones we
    # touched. Pulling the ids before the DELETE keeps the recompute
    # below tightly scoped (a profile that never collected duplicates
    # is skipped entirely). ``deal_id IS NOT NULL`` matches the
    # eventual UNIQUE constraint's binding set.
    affected_target_ids = [
        row[0]
        for row in bind.execute(
            text(
                """
                SELECT DISTINCT target_id
                FROM reviews
                WHERE deal_id IS NOT NULL
                  AND (author_id, deal_id) IN (
                    SELECT author_id, deal_id
                    FROM reviews
                    WHERE deal_id IS NOT NULL
                    GROUP BY author_id, deal_id
                    HAVING COUNT(*) > 1
                  )
                """
            )
        ).fetchall()
    ]

    # Step 2 — keep the lowest-id row per ``(author_id, deal_id)`` and
    # delete the rest. Rows with ``deal_id IS NULL`` are excluded from
    # the dedup so historical cascade-NULLed rows are preserved (they
    # don't violate the upcoming UNIQUE because Postgres treats NULL
    # as distinct).
    bind.execute(
        text(
            """
            DELETE FROM reviews r
            USING (
                SELECT author_id, deal_id, MIN(id) AS keep_id
                FROM reviews
                WHERE deal_id IS NOT NULL
                GROUP BY author_id, deal_id
                HAVING COUNT(*) > 1
            ) d
            WHERE r.author_id = d.author_id
              AND r.deal_id = d.deal_id
              AND r.id <> d.keep_id
            """
        )
    )

    # Step 3 — recompute ``good`` / ``bad`` on each affected target so
    # the materialised counters reflect the deduped review set. We use
    # the same boundary ``services.recompute_user_rating`` uses
    # (rating >= 4 → good, rating <= 2 → bad, rating == 3 → neutral)
    # so the projection stays consistent with the runtime path. Doing
    # it inside the same transaction means the post-migration DB is
    # internally consistent even if no user posts a fresh review for
    # a while.
    if affected_target_ids:
        bind.execute(
            text(
                """
                UPDATE users u
                SET good = COALESCE(s.good, 0),
                    bad = COALESCE(s.bad, 0)
                FROM (
                    SELECT
                        target_id,
                        COUNT(*) FILTER (WHERE rating >= 4) AS good,
                        COUNT(*) FILTER (WHERE rating <= 2) AS bad
                    FROM reviews
                    WHERE target_id = ANY(:ids)
                    GROUP BY target_id
                ) s
                WHERE u.id = s.target_id
                """
            ),
            {"ids": affected_target_ids},
        )
        # Zero out the counters for any affected target that no longer
        # has any reviews at all (the subquery above produces no row
        # for them, so the UPDATE wouldn't touch ``users.good`` /
        # ``users.bad`` — which would leave stale counts behind).
        bind.execute(
            text(
                """
                UPDATE users
                SET good = 0, bad = 0
                WHERE id = ANY(:ids)
                  AND NOT EXISTS (
                    SELECT 1 FROM reviews WHERE target_id = users.id
                  )
                """
            ),
            {"ids": affected_target_ids},
        )

    # Step 4 — install the UNIQUE constraint. With duplicates gone
    # this DDL is a no-op at the data layer; it only matters for
    # future writes. Mirrors the ``Review.__table_args__`` declaration
    # in ``backend/app/models.py``.
    op.create_unique_constraint(
        "uq_reviews_author_deal",
        "reviews",
        ["author_id", "deal_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_reviews_author_deal", "reviews", type_="unique")
