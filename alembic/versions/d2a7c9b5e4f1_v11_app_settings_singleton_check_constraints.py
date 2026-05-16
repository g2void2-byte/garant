"""V11-H-6 / V11-M-8 / V11-M-9 / V11-L-3 — singleton + CHECK constraints.

Three independent fixes from the v11 audit, batched into one
revision so a single migration restart picks all of them up.

* **V11-H-6 — ``app_settings`` singleton.** The application has
  always treated ``app_settings`` as a single-row table by
  convention (``select().limit(1)``, "create if missing" in
  ``_settings``), but nothing in the schema prevented two parallel
  lifespan starts on a fresh DB from each inserting their own row.
  This migration adds a partial unique index on the constant
  expression ``true``, which Postgres enforces as "at most one row
  in this table ever". The migration also deletes any rogue rows
  past the lowest-id one (only possible on a DB that has already
  hit the race) so the index can be created without error.

* **V11-M-8 — ``reviews.rating`` 1..5 CHECK.** The model declared
  ``rating: Mapped[int]`` with no bounds; ``_recompute_user_rating``
  trusts the data to be in 1..5. An admin SQL update that wrote a
  9 or a 0 would (a) silently pass and (b) corrupt the aggregate
  rating calculation downstream.

* **V11-M-9 — ``users.rating_manual`` 0..5 CHECK.** Same shape:
  ``Numeric(3, 2)`` accepts 0.00..9.99, but the UI renders it as
  ``X.YZ / 5``. A typo on the admin form (``9.5`` instead of
  ``4.5``) currently has no defence-in-depth.

* **V11-L-3 — ``users.deals_*`` non-negative CHECKs.** The
  V11-H-3 fix in ``services_deals.py`` switched counter bumps to
  ``UPDATE users SET deals_total = deals_total + 1``, which is
  serialised by Postgres. The CHECKs here close the matching gap
  on the schema side: a bug or admin-side SQL that tries to write
  a negative count fails at constraint time instead of producing
  a profile page that says "user has -2 successful deals".

Revision ID: d2a7c9b5e4f1
Revises: a1b2c3d4e5f6
Create Date: 2026-05-16 20:55:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2a7c9b5e4f1"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # V11-H-6 — collapse any duplicate ``app_settings`` rows the race
    # may have already created, then create the partial unique index.
    # If only one row exists the DELETE is a no-op; the index then
    # makes "at most one row" a schema invariant.
    bind.execute(
        sa.text(
            "DELETE FROM app_settings "
            "WHERE id NOT IN (SELECT id FROM app_settings ORDER BY id LIMIT 1)"
        )
    )
    op.create_index(
        "ix_app_settings_singleton",
        "app_settings",
        [sa.text("(true)")],
        unique=True,
    )

    # V11-M-8 — defence-in-depth for the ratings aggregate. ``5`` is
    # the user-visible max in the UI; ``1`` is the min (a 0 would
    # render as an empty starred row and is treated as "no review"
    # by the aggregator).
    op.create_check_constraint(
        "ck_reviews_rating_range",
        "reviews",
        "rating BETWEEN 1 AND 5",
    )

    # V11-M-9 — same shape on the manual-override column. ``NULL``
    # means "no override, fall back to computed rating", so the
    # constraint allows NULL but bounds non-NULL values.
    op.create_check_constraint(
        "ck_users_rating_manual_range",
        "users",
        "rating_manual IS NULL OR rating_manual BETWEEN 0 AND 5",
    )

    # V11-L-3 — the deal-outcome counters are written by application
    # code via ``UPDATE ... SET col = col + 1``. A negative value
    # cannot legitimately arise; if one does, fail fast at the DB.
    op.create_check_constraint(
        "ck_users_deals_total_nonneg",
        "users",
        "deals_total >= 0",
    )
    op.create_check_constraint(
        "ck_users_deals_success_nonneg",
        "users",
        "deals_success >= 0",
    )
    op.create_check_constraint(
        "ck_users_deals_failed_nonneg",
        "users",
        "deals_failed >= 0",
    )
    op.create_check_constraint(
        "ck_users_deals_arbitrage_nonneg",
        "users",
        "deals_arbitrage >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_deals_arbitrage_nonneg", "users", type_="check")
    op.drop_constraint("ck_users_deals_failed_nonneg", "users", type_="check")
    op.drop_constraint("ck_users_deals_success_nonneg", "users", type_="check")
    op.drop_constraint("ck_users_deals_total_nonneg", "users", type_="check")
    op.drop_constraint("ck_users_rating_manual_range", "users", type_="check")
    op.drop_constraint("ck_reviews_rating_range", "reviews", type_="check")
    op.drop_index("ix_app_settings_singleton", table_name="app_settings")
