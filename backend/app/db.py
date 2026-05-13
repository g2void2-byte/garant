from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from alembic import command

from .config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _alembic_config() -> Config:
    """Return the project's alembic config with the live DATABASE_URL injected.

    Picks up ``alembic.ini`` from the repository root irrespective of the
    current working directory so this also works when uvicorn is launched
    from elsewhere.
    """
    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
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


def _redact_dsn(url: str) -> str:
    """Strip the password from a database URL for safe logging."""
    if "@" in url and "://" in url:
        head, _, rest = url.partition("://")
        creds, _, hostpart = rest.partition("@")
        if ":" in creds:
            user, _, _ = creds.partition(":")
            return f"{head}://{user}:***@{hostpart}"
    return url
