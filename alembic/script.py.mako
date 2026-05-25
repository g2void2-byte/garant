"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

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

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
