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
    if inspector.has_table("users"):
        existing = {col["name"] for col in inspector.get_columns("users")}
        for col, ddl in [
            ("pin_hash", "VARCHAR(255)"),
            ("pin_attempts", "INTEGER NOT NULL DEFAULT 0"),
            ("pin_locked_until", "DATETIME"),
            ("pin_reset_code_hash", "VARCHAR(255)"),
            ("pin_reset_expires", "DATETIME"),
        ]:
            if col not in existing:
                sync_conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {ddl}"))

    if inspector.has_table("deals"):
        existing = {col["name"] for col in inspector.get_columns("deals")}
        for col, ddl in [
            ("currency_id", "INTEGER"),
            ("amount", "NUMERIC(28, 8)"),
            ("commission_amount", "NUMERIC(28, 8)"),
            ("in_progress_at", "DATETIME"),
            ("cancellation_initiator_id", "INTEGER"),
            ("cancellation_reason", "TEXT"),
            ("cancellation_requested_at", "DATETIME"),
            ("arbitration_initiator_id", "INTEGER"),
            ("arbitration_reason", "TEXT"),
            ("arbitration_resolved_by", "INTEGER"),
            ("arbitration_resolution", "VARCHAR(16)"),
            ("arbitration_resolved_at", "DATETIME"),
        ]:
            if col not in existing:
                sync_conn.execute(text(f"ALTER TABLE deals ADD COLUMN {col} {ddl}"))

        # Map legacy statuses (5-state machine) onto the new 10-state machine
        # in a single sweep. Idempotent: rows already migrated are no-ops.
        sync_conn.execute(
            text(
                "UPDATE deals SET status = 'pending_confirmation' "
                "WHERE status = 'wait_confirm'"
            )
        )
        sync_conn.execute(
            text(
                "UPDATE deals SET status = 'in_progress' WHERE status = 'confirmed'"
            )
        )
        sync_conn.execute(
            text("UPDATE deals SET status = 'completed' WHERE status = 'success'")
        )
        sync_conn.execute(
            text("UPDATE deals SET status = 'cancelled' WHERE status = 'failed'")
        )
        sync_conn.execute(
            text(
                "UPDATE deals SET status = 'arbitration' WHERE status = 'arbitrage'"
            )
        )

    if inspector.has_table("app_settings"):
        existing = {col["name"] for col in inspector.get_columns("app_settings")}
        for col, ddl in [
            (
                "inactivity_pending_confirmation_days",
                "INTEGER NOT NULL DEFAULT 7",
            ),
            (
                "inactivity_pending_cancellation_days",
                "INTEGER NOT NULL DEFAULT 3",
            ),
            (
                "max_active_services_per_user",
                "INTEGER NOT NULL DEFAULT 10",
            ),
        ]:
            if col not in existing:
                sync_conn.execute(
                    text(f"ALTER TABLE app_settings ADD COLUMN {col} {ddl}")
                )

    if inspector.has_table("services"):
        existing = {col["name"] for col in inspector.get_columns("services")}
        for col, ddl in [
            ("status", "VARCHAR(16) NOT NULL DEFAULT 'active'"),
            ("ban_reason", "TEXT"),
        ]:
            if col not in existing:
                sync_conn.execute(
                    text(f"ALTER TABLE services ADD COLUMN {col} {ddl}")
                )
