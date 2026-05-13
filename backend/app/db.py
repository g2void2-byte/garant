from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def create_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_lightweight_migrations)


def _apply_lightweight_migrations(sync_conn) -> None:
    """Add new nullable columns to existing tables without losing data.

    SQLAlchemy's create_all is a no-op for existing tables, so any new
    columns we add to Mapped models must be applied here. Only safe for
    nullable / defaulted columns.
    """
    inspector = inspect(sync_conn)
    if not inspector.has_table("users"):
        return
    existing = {col["name"] for col in inspector.get_columns("users")}
    additions = [
        ("pin_hash", "VARCHAR(255)"),
        ("pin_attempts", "INTEGER NOT NULL DEFAULT 0"),
        ("pin_locked_until", "DATETIME"),
        ("pin_reset_code_hash", "VARCHAR(255)"),
        ("pin_reset_expires", "DATETIME"),
    ]
    for col, ddl in additions:
        if col not in existing:
            sync_conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {ddl}"))
