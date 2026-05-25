"""Audit §15.1 — apply ``ON DELETE CASCADE`` to FKs declared in ``models.py``

The SQLAlchemy ORM declarations on the following ``ForeignKey`` columns
carry ``ondelete="CASCADE"`` (see ``backend/app/models.py``) but the
matching constraints in PostgreSQL were created without an ``ON
DELETE`` action — the ORM-side keyword is purely documentary unless an
Alembic migration applies it to the actual constraint. The mismatch is
load-bearing: ``services_account.confirm_transfer`` relies on
``DELETE FROM users WHERE id = :target_id`` cascading to every child
row of the empty target shell (see the ``M-13`` comment in
``confirm_transfer``); without the DB-side cascades the delete trips
``IntegrityError`` the moment the target already has, say, a single
welcome notification row.

FKs hardened by this revision (all → ``users.id`` with ``CASCADE``):

* ``services.owner_id``
* ``notifications.recipient_id``
* ``forums.owner_id``
* ``media.owner_id``
* ``user_balances.user_id``
* ``wallet_deposits.user_id``
* ``wallet_withdrawals.user_id``

``service_comments.author_id`` and ``reviews.{author_id,target_id}``
already received the same treatment in ``r9a3b6c2d8e1`` and are not
touched here. ``admin_audit_log.actor_id`` uses ``SET NULL`` (forensic
trail outlives the actor) and is also left alone.

V5-E-1 — irreversible policy change on downgrade

The downgrade rebuilds the FKs without an ``ON DELETE`` action,
matching the pre-upgrade state. No row data is lost or modified.
Application code calling ``session.delete(user)`` on a user with
existing child rows will start failing again after a downgrade — that
is the pre-upgrade behaviour the model annotations were trying to
escape from.

Revision ID: v4b5c6d7e8f9
Revises: u3a4b5c6d7e8
Create Date: 2026-05-21 23:00:00.000000
"""

from __future__ import annotations

from typing import Sequence

from alembic import op

revision: str = "v4b5c6d7e8f9"
down_revision: str | None = "u3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (constraint_name, table, column) — matches the auto-generated
# Postgres FK names from the initial schema (``{table}_{column}_fkey``).
_USER_FK_CASCADES: tuple[tuple[str, str, str], ...] = (
    ("services_owner_id_fkey", "services", "owner_id"),
    ("notifications_recipient_id_fkey", "notifications", "recipient_id"),
    ("forums_owner_id_fkey", "forums", "owner_id"),
    ("media_owner_id_fkey", "media", "owner_id"),
    ("user_balances_user_id_fkey", "user_balances", "user_id"),
    ("wallet_deposits_user_id_fkey", "wallet_deposits", "user_id"),
    ("wallet_withdrawals_user_id_fkey", "wallet_withdrawals", "user_id"),
)


def upgrade() -> None:
    for fk_name, table, column in _USER_FK_CASCADES:
        op.drop_constraint(fk_name, table, type_="foreignkey")
        op.create_foreign_key(
            fk_name,
            table,
            "users",
            [column],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    for fk_name, table, column in _USER_FK_CASCADES:
        op.drop_constraint(fk_name, table, type_="foreignkey")
        op.create_foreign_key(
            fk_name,
            table,
            "users",
            [column],
            ["id"],
        )
