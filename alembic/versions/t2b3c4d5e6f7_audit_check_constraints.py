"""Audit follow-up: defensive CHECK constraints on user-supplied fields

Audit v12 §15.5 / §15.6 / §15.7 — three free-form columns whose
allowed value set was previously only enforced at the application
layer. The CHECK constraints below act as a defence-in-depth so a
direct SQL write (ad-hoc fix, future ORM bug, replication script)
cannot land a row the API would otherwise reject.

* ``users.country`` — ``NULL`` or an uppercase ISO-3166-1 alpha-2
  code (``^[A-Z]{2}$``). The frontend country picker only emits
  uppercase codes, but the column was a bare ``VARCHAR(2)``.
* ``wallet_deposits.purpose`` — closed set ``{'wallet', 'trust'}``
  matching the ``WalletDepositCreateReq.purpose`` ``Literal``. We
  deliberately keep the column as plain ``VARCHAR(16)`` (not a
  Postgres enum) so adding a third purpose stays a one-line
  migration; the CHECK constraint just pins the current set.
* ``services.photo_urls`` — JSONB array of at most
  ``MAX_SERVICE_PHOTOS`` (6) entries, matching the existing
  ``_validate_service_photos`` cap in
  ``backend/app/schemas.py``.

All three are pure ADD CONSTRAINT statements — no data migration —
so the upgrade is fast and the downgrade is a clean DROP. The
upgrade validates existing rows; if a legacy row would fail (e.g.
a lowercase ``users.country`` from before the FE picker shipped),
the migration will refuse to apply and the operator must clean the
data first. This is intentional: silently coercing user-supplied
data during a migration would lose the offending value.

Revision ID: t2b3c4d5e6f7
Revises: s1a2b3c4d5e6
Create Date: 2026-05-21 20:30:00.000000
"""

from __future__ import annotations

from typing import Sequence

from alembic import op

revision: str = "t2b3c4d5e6f7"
down_revision: str | None = "s1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_users_country_iso_alpha2",
        "users",
        "country IS NULL OR country ~ '^[A-Z]{2}$'",
    )
    op.create_check_constraint(
        "ck_wallet_deposits_purpose_known",
        "wallet_deposits",
        "purpose IN ('wallet', 'trust')",
    )
    # ``jsonb_array_length`` raises on non-array input, so we also
    # guard the type with ``jsonb_typeof`` — defensive against a
    # legacy row that managed to land a non-array value (the column
    # is ``NOT NULL`` with a ``'[]'`` server_default so realistically
    # every row is an array, but treat this as a paranoid invariant).
    op.create_check_constraint(
        "ck_services_photo_urls_max_6",
        "services",
        "jsonb_typeof(photo_urls) = 'array' AND jsonb_array_length(photo_urls) <= 6",
    )


def downgrade() -> None:
    op.drop_constraint("ck_services_photo_urls_max_6", "services", type_="check")
    op.drop_constraint("ck_wallet_deposits_purpose_known", "wallet_deposits", type_="check")
    op.drop_constraint("ck_users_country_iso_alpha2", "users", type_="check")
