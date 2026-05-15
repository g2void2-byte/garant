"""Alembic environment configured for the async SQLAlchemy engine.

We import ``Base`` from the app so ``--autogenerate`` sees the full
model metadata. The database URL comes from ``settings.database_url``
(populated by env / `.env`) rather than from ``alembic.ini``.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import all models so ``Base.metadata`` is fully populated for
# autogenerate. Re-exports aren't relied on; the import itself is the
# side effect we need.
from backend.app import models  # noqa: F401, E402
from backend.app.config import settings  # noqa: E402
from backend.app.db import Base  # noqa: E402

# V5-D-9 — fixed advisory-lock key. ``pg_advisory_lock(bigint)`` takes
# any signed 64-bit integer; we use a constant unique to this codebase
# so two ``alembic upgrade head`` processes during a rolling deploy
# serialise on the same key. Computed once via
# ``hashtext('garant_alembic_migrations')`` — written as a literal to
# avoid an extra SELECT round-trip at every Alembic invocation.
_ALEMBIC_ADVISORY_LOCK = 7237_4203_1881_4729

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to a database."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    # V5-D-9 (M) — serialize concurrent ``alembic upgrade`` calls via
    # a PostgreSQL session-level advisory lock. During a rolling
    # deploy the new container can start before the old one has
    # exited, and both ``CMD ["alembic", "upgrade", "head"]`` will
    # race. The two-step ``ALTER TYPE`` / ``UPDATE`` migrations we
    # use today are NOT idempotent under concurrency — a second
    # writer can see the old enum, try to insert the new value, and
    # crash with ``unsafe_use_of_new_value_of_enum_type``. Holding
    # the advisory lock for the duration of the upgrade is the
    # smallest change that closes the window. The lock is acquired
    # INSIDE ``begin_transaction`` so the txn boundaries Alembic
    # manages (which differ between ``transactional_ddl`` and
    # legacy modes) wrap both the lock and the migration ops.
    is_postgres = connection.dialect.name == "postgresql"
    with context.begin_transaction():
        if is_postgres:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=_ALEMBIC_ADVISORY_LOCK)
            )
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
