"""merge: reviews_unique + p5_p10_commission_via_invoice heads

Revision ID: a16d9c908a5f
Revises: aa1b2c3d4e5f, za1b2c3d4e5f
Create Date: 2026-05-24 12:34:22.991681

V12-I11 — contract reminders before you write the migration body:

* If ``downgrade()`` drops a column, drops an enum value, or otherwise
  coerces data into a smaller domain than ``upgrade()`` produced,
  copy the marker line below verbatim into this docstring (the
  ``tests/test_v5_d_e_bucket.py::test_destructive_migrations_document_irreversible_data_loss``
  contract grep-matches the literal string and will fail the build
  otherwise):

      V5-E-1 — irreversible data loss on downgrade

  Then list which column / enum value will not survive the downgrade
  so an operator running ``alembic downgrade`` against production
  sees the warning before they run it.

* ``CREATE INDEX`` on a non-empty table holds an ``AccessExclusiveLock``
  for the duration of the build. Use the ``op.get_context().autocommit_block()``
  + ``postgresql_concurrently=True`` pattern (and ``if_not_exists=True`` /
  ``if_exists=True`` on the matching ``drop_index``) so the migration
  is non-blocking. The contract test
  ``test_concurrent_index_migrations_use_autocommit_and_concurrently``
  walks the allow-listed migrations and asserts those tokens are
  present.

* ``CREATE INDEX CONCURRENTLY`` cannot run inside a transaction, so
  Alembic refuses to invoke it without the ``autocommit_block``. A
  forgotten ``autocommit_block`` shows up as ``CREATE INDEX
  CONCURRENTLY cannot run inside a transaction block`` at apply time
  — there is no way to "fix it on the next migration"; you have to
  edit this file before merging.
"""

from __future__ import annotations

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "a16d9c908a5f"
down_revision: Union[str, None] = ("aa1b2c3d4e5f", "za1b2c3d4e5f")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
