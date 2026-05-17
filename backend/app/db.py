from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from alembic import command

from .config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, echo=False)
# V11-M-19 — ``expire_on_commit=False`` keeps attribute access cheap
# after ``await session.commit()``: SQLAlchemy doesn't invalidate
# loaded columns, so a follow-up ``obj.some_field`` doesn't have to
# issue a SELECT. The tradeoff is that the in-memory ``obj`` is now
# free to drift from the DB row (another transaction can update it
# mid-flight, or the commit itself can change a value via
# ``DEFAULT`` / triggers / ``RETURNING``). Whenever the next code
# path needs the canonical row state — usually right after the
# commit that triggered a row-level change we then want to read —
# call ``await session.refresh(obj)`` (or re-fetch via
# ``session.get``). The notifier / serialiser layer assumes the
# attribute access is non-blocking; refresh() is the explicit
# escape hatch when we want a fresh read. New writers MUST audit
# their post-commit reads against this rule.
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


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
    logger.info("running alembic upgrade head against %s", _redact_dsn(settings.database_url))
    await asyncio.to_thread(_upgrade_to_head_sync)
    logger.info("alembic upgrade head complete")


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
        logger.warning("alembic script directory has no head revision; skipping DB version check")
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
        async with engine.begin() as conn:
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
    logger.info("alembic version check OK: DB at %s", current)


def _redact_dsn(url: str) -> str:
    """Strip the password from a database URL for safe logging."""
    if "@" in url and "://" in url:
        head, _, rest = url.partition("://")
        creds, _, hostpart = rest.partition("@")
        if ":" in creds:
            user, _, _ = creds.partition(":")
            return f"{head}://{user}:***@{hostpart}"
    return url
