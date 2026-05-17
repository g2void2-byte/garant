from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from alembic import command

from .config import settings

logger = logging.getLogger(__name__)

# V11-M-18 — the engine + sessionmaker are constructed *lazily* on
# first access rather than at module import. Pre-fix the line read
# ``engine = create_async_engine(settings.database_url, ...)`` at
# module top-level, so any ``import backend.app.db`` (including the
# transitive ones triggered by importing a router) materialised an
# asyncpg engine bound to whatever ``DATABASE_URL`` was set at *that*
# moment. The test harness has to set the env var before any router
# import to pin the URL to the dedicated ``garant_test`` database;
# anything that re-orders imports (a new global helper, a tool that
# eagerly walks the package) would silently bind to the production
# URL. Deferring the constructor to a singleton accessor closes that
# hole — ``get_engine()`` reads ``settings.database_url`` on first
# call, which (a) happens inside the lifespan / fixture setup, and
# (b) can be reset by tests via ``reset_engine_for_tests`` without
# leaking a half-initialised engine into the next event loop.
#
# Backwards-compat: existing call sites ``from .db import engine`` /
# ``from .db import async_session`` still work thanks to the module
# ``__getattr__`` below — the first access materialises the singletons
# transparently.
_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, constructing on first call.

    See the V11-M-18 note above for why this is lazy.
    """
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.database_url, echo=False)
    return _engine


def get_async_session() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide sessionmaker, constructing on first call.

    V11-M-19 — ``expire_on_commit=False`` keeps attribute access cheap
    after ``await session.commit()``: SQLAlchemy doesn't invalidate
    loaded columns, so a follow-up ``obj.some_field`` doesn't have to
    issue a SELECT. The tradeoff is that the in-memory ``obj`` is now
    free to drift from the DB row (another transaction can update it
    mid-flight, or the commit itself can change a value via
    ``DEFAULT`` / triggers / ``RETURNING``).

    L-19 — combined with SA 2.0 + asyncpg "eager defaults" RETURNING,
    this means INSERTs already populate the ORM instance with every
    ``server_default``-backed column (``created_at``, enum defaults,
    bigint counters, …) without a follow-up SELECT. ``UPDATE``\\s do
    NOT auto-fetch ``onupdate=`` values; if your code needs the
    DB-side ``updated_at`` (or any other column written by an
    ``onupdate`` clause / trigger / external transaction), reach for
    the *narrow* form ``await session.refresh(obj,
    attribute_names=[...])`` so the reload only re-issues a SELECT
    for the column(s) you actually need.

    Plain ``await session.refresh(obj)`` post-commit is redundant
    under this configuration — it round-trips the DB for columns the
    ORM already has. Use the narrow ``attribute_names=`` form
    whenever you genuinely need a fresh read, or fall through and
    let ``expire_on_commit=False`` serve the cached values. The
    regression test in ``tests/test_l19_no_redundant_refresh.py``
    enforces this by checking every ``session.refresh`` call site
    against an explicit allowlist.
    """
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_factory


async def reset_engine_for_tests() -> None:
    """Dispose the engine's connection pool without rebuilding the engine.

    Test-only hook. pytest-asyncio creates a fresh event loop per
    test function; pooled asyncpg connections opened on the previous
    test's (now-closed) loop raise "Future attached to a different
    loop" when reused. The dispose-and-reuse pattern below clears the
    pool while keeping the engine *object* stable, so any module that
    captured ``async_session`` at import time continues to use the
    same factory — the next ``engine.begin()`` (or ``async_session()``
    call) opens a fresh connection bound to the current loop.

    We deliberately do NOT reset the singletons to ``None`` here:
    ``from backend.app.db import async_session`` caches the factory
    reference inside the importing module, so swapping the underlying
    factory object would leave those callers pointing at a discarded
    instance. Disposing the pool is the safe, minimally-invasive
    pattern that worked for the pre-M-18 module-level engine and
    keeps working for the lazily-initialised one.
    """
    if _engine is not None:
        # ``close=False`` skips the per-connection close (which would
        # try to await each pooled connection's ``.close()`` on the
        # *current* loop, raising "got Future attached to a different
        # loop" when those connections were opened on the previous
        # test's loop). With ``close=False`` we just drop the pool's
        # references; asyncpg's protocol objects are GC'd later. The
        # tradeoff is one log line per orphaned connection during the
        # interpreter's eventual cleanup, which is acceptable for a
        # test-only helper.
        try:
            await _engine.dispose(close=False)
        except (RuntimeError, OSError):
            pass


def __getattr__(name: str) -> Any:
    """Module-level attribute access — expose ``engine`` / ``async_session``.

    PEP-562 hook so legacy call sites that do
    ``from backend.app.db import engine`` (or ``async_session``)
    transparently materialise the singleton on first reference. The
    accessors above are the canonical entry points for new code.
    """
    if name == "engine":
        return get_engine()
    if name == "async_session":
        return get_async_session()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class Base(DeclarativeBase):
    pass


def _alembic_root() -> Path:
    """Locate the directory that holds ``alembic.ini`` + ``alembic/``.

    V11-L-9 — historically this was hard-coded to
    ``Path(__file__).resolve().parents[2]``, which is fine when the
    package is editable-installed from the source tree (``parents[2]``
    points at the repo root) but breaks the moment the package is
    installed into ``site-packages`` (``parents[2]`` then points at
    ``…/lib/python3.x/site-packages`` which has no ``alembic.ini``).
    Allowing ``GARANT_ALEMBIC_ROOT`` to override gives non-editable
    installs (k8s images that COPY only the ``backend/`` tree, ad-hoc
    one-shot containers, etc.) a way to point at the migration root
    without re-vendoring the layout. The fallback still resolves
    relative to ``__file__`` so the source-tree happy path is
    unchanged.
    """
    override = os.environ.get("GARANT_ALEMBIC_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    """Return the project's alembic config with the live DATABASE_URL injected.

    Picks up ``alembic.ini`` from the repository root irrespective of the
    current working directory so this also works when uvicorn is launched
    from elsewhere.
    """
    root = _alembic_root()
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


def _upgrade_to_head_sync() -> None:
    command.upgrade(_alembic_config(), "head")


async def run_migrations() -> None:
    """Run ``alembic upgrade head`` in a worker thread.

    The alembic CLI is synchronous and opens its own async engine in
    ``env.py``, so we cannot call it directly from a running event loop.
    Off-loading to a thread keeps lifespan startup non-blocking.
    """
    # V11-L-15 — structured-logging fields so the JSON-logger
    # downstream (Loki/Sentry) can pivot on event without regexing
    # the message body. The DSN is redacted before being attached
    # so the password is never written to ``extra``.
    redacted_dsn = _redact_dsn(settings.database_url)
    logger.info(
        "running alembic upgrade head against %s",
        redacted_dsn,
        extra={"event": "alembic.upgrade.start", "database_dsn": redacted_dsn},
    )
    await asyncio.to_thread(_upgrade_to_head_sync)
    logger.info(
        "alembic upgrade head complete",
        extra={"event": "alembic.upgrade.ok", "database_dsn": redacted_dsn},
    )


def _expected_alembic_head() -> str:
    """Return the alembic head revision recorded in ``alembic/versions``.

    Resolved from the script directory rather than the live DB so the
    sanity check below can answer "is the DB at the version this build
    of the code expects?" — exactly the question an init-container /
    one-shot migration step leaves open.
    """
    return ScriptDirectory.from_config(_alembic_config()).get_current_head() or ""


async def verify_migrations_at_head() -> None:
    """Verify the DB is migrated to the head revision this build expects.

    V12-H3 — used when ``RUN_MIGRATIONS_ON_STARTUP=false`` (compose
    runs migrations in a dedicated one-shot service so each replica's
    lifespan does not race on the same advisory lock). Reads
    ``alembic_version`` directly so we don't depend on the synchronous
    alembic CLI inside an async lifespan.

    Raises :class:`RuntimeError` if the table is missing or the DB
    version differs from the script-directory head — anything else is
    a foot-gun (operator forgot to run migrations / pinned to an old
    image / mismatched code-vs-DB).
    """
    expected = _expected_alembic_head()
    if not expected:
        # Empty ``alembic/versions`` — nothing to verify against.
        # V11-L-15 — structured-logging fields so the JSON-logger
        # downstream (Loki/Sentry) can pivot on event without
        # regexing the message body.
        logger.warning(
            "alembic script directory has no head revision; skipping DB version check",
            extra={"event": "alembic.verify.no_head_revision"},
        )
        return

    # Pre-fix the bare ``SELECT`` propagated SQLAlchemy's
    # ``ProgrammingError`` (wrapping asyncpg's ``UndefinedTableError``)
    # when ``alembic_version`` didn't exist — typically a first boot
    # against a fresh DB without the compose ``migrate`` service. The
    # docstring above promises ``RuntimeError`` with a remediation
    # hint; the raw driver error gave operators a stack trace and no
    # signal pointing at the actual fix. Catching ``ProgrammingError``
    # narrowly (rather than the broader ``DBAPIError``) keeps real
    # connectivity / auth failures bubbling up as-is so they're not
    # misattributed to a missing migration.
    try:
        async with get_engine().begin() as conn:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            rows = result.scalars().all()
    except ProgrammingError as exc:
        raise RuntimeError(
            "alembic_version table does not exist — run 'alembic upgrade head' "
            f"before starting the API (expected head: {expected}). "
            "Compose users: the 'migrate' init-service is responsible for this; "
            "manual setups can set RUN_MIGRATIONS_ON_STARTUP=true."
        ) from exc

    if not rows:
        raise RuntimeError(
            "alembic_version table is empty — run 'alembic upgrade head' "
            f"before starting the API (expected head: {expected}). "
            "Compose users: the 'migrate' init-service is responsible for this; "
            "manual setups can set RUN_MIGRATIONS_ON_STARTUP=true."
        )
    current = rows[0]
    if current != expected:
        raise RuntimeError(
            f"DB at alembic revision {current!r} but this build expects {expected!r}. "
            "Run 'alembic upgrade head' (or restart the compose 'migrate' service) "
            "to bring the DB to head before starting the API."
        )
    # V11-L-15 — structured-logging fields so the JSON-logger
    # downstream (Loki/Sentry) can pivot on event/revision without
    # regexing the message body. ``current`` is short (alembic rev id)
    # so attaching it to ``extra`` is safe — cardinality is bounded
    # by the number of revisions in the script directory.
    logger.info(
        "alembic version check OK: DB at %s",
        current,
        extra={
            "event": "alembic.verify.ok",
            "current_revision": current,
            "expected_revision": expected,
        },
    )


def _redact_dsn(url: str) -> str:
    """Strip the password from a database URL for safe logging."""
    if "@" in url and "://" in url:
        head, _, rest = url.partition("://")
        creds, _, hostpart = rest.partition("@")
        if ":" in creds:
            user, _, _ = creds.partition(":")
            return f"{head}://{user}:***@{hostpart}"
    return url
