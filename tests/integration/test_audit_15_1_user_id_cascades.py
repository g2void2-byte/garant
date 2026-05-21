"""Audit §15.1 — verify the model declares + the DB applies ``ON DELETE
CASCADE`` on every FK from a child table to ``users.id`` that the
audit flagged.

The audit found that the SQLAlchemy ORM-side ``ondelete="CASCADE"``
keyword was set on several FKs (``services.owner_id``,
``notifications.recipient_id``, ``forums.owner_id``, ``media.owner_id``,
``user_balances.user_id``, ``wallet_deposits.user_id``,
``wallet_withdrawals.user_id``) but no Alembic migration had applied
those policies to the actual PostgreSQL constraints. As a result,
``services_account.confirm_transfer`` would trip ``IntegrityError``
the moment the target user had even a single welcome notification
attached — directly contradicting the ``M-13`` comment in
``confirm_transfer`` that claimed cascades handled child-row cleanup.

These tests pin both halves of the contract:

1. The model annotation is the source of truth for *intent*.
2. The committed migration ``v4b5c6d7e8f9`` is the source of truth
   for *enforcement*.
3. The actual PostgreSQL ``pg_constraint`` row carries ``confdeltype
   = 'c'`` (= CASCADE) for each FK.
4. ``DELETE FROM users WHERE id = …`` succeeds end-to-end against a
   user that owns at least one of each child kind, with no manual
   pre-cleanup.
"""

from __future__ import annotations

import pathlib

import pytest
from sqlalchemy import delete, select, text

from backend.app.db import async_session
from backend.app.models import (
    Forum,
    Media,
    Notification,
    NotificationType,
    Service,
    ServiceStatus,
    User,
    UserBalance,
    WalletDeposit,
    WalletDepositProvider,
    WalletDepositStatus,
    WalletWithdrawal,
    WalletWithdrawStatus,
)
from tests.helpers import auth_headers, signed_init_data

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


# Each entry is ``(model_class, column_name)`` — every one declares
# ``ondelete="CASCADE"`` in ``models.py`` and is touched by the new
# migration.
_USER_CASCADE_FKS = (
    (Service, "owner_id"),
    (Notification, "recipient_id"),
    (Forum, "owner_id"),
    (Media, "owner_id"),
    (UserBalance, "user_id"),
    (WalletDeposit, "user_id"),
    (WalletWithdrawal, "user_id"),
)


@pytest.mark.parametrize(("model", "column"), _USER_CASCADE_FKS)
async def test_model_annotation_declares_user_id_cascade(model, column):
    """The model is the source of truth for intent. ``confirm_transfer``
    relies on every entry below cascading on user delete."""
    col = model.__table__.columns[column]
    fks = list(col.foreign_keys)
    assert len(fks) == 1, f"{model.__tablename__}.{column} should have exactly one FK"
    assert fks[0].column.table.name == "users"
    assert fks[0].ondelete == "CASCADE", (
        f"{model.__tablename__}.{column} model annotation must be ondelete=CASCADE"
    )


@pytest.mark.parametrize(("model", "column"), _USER_CASCADE_FKS)
async def test_db_constraint_applies_user_id_cascade(model, column):
    """The migration must have applied ``ON DELETE CASCADE`` on the
    actual constraint, not just left the ORM keyword as documentation.
    ``pg_constraint.confdeltype`` values: ``a`` (no action / default),
    ``r`` (restrict), ``c`` (cascade), ``n`` (set null), ``d`` (set
    default)."""
    table = model.__tablename__
    constraint_name = f"{table}_{column}_fkey"
    async with async_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT confdeltype FROM pg_constraint WHERE conname = :name AND contype = 'f'"
                ),
                {"name": constraint_name},
            )
        ).one_or_none()
    assert row is not None, f"Foreign key {constraint_name} is missing from pg_constraint"
    # ``pg_constraint.confdeltype`` is a Postgres ``"char"`` (single-
    # byte) column; ``asyncpg`` surfaces it as ``bytes`` while
    # ``psycopg`` would surface it as ``str``. Coerce on the test
    # side so the assertion works regardless of driver.
    value = row[0].decode("ascii") if isinstance(row[0], (bytes, bytearray)) else row[0]
    assert value == "c", (
        f"Foreign key {constraint_name} has confdeltype={row[0]!r}, expected 'c' (CASCADE)"
    )


async def test_migration_file_exists_with_expected_revision():
    """Pin the committed migration file so a future ``--autogenerate``
    rerun does not silently re-create it under a different name."""
    path = REPO_ROOT / "alembic" / "versions" / "v4b5c6d7e8f9_apply_user_id_cascades.py"
    assert path.exists()
    text_body = path.read_text()
    assert 'revision: str = "v4b5c6d7e8f9"' in text_body
    assert 'down_revision: str | None = "u3a4b5c6d7e8"' in text_body
    # Every FK enumerated by the test parametrisation must appear in
    # the migration body so a future edit cannot drop a column without
    # a matching test update.
    for model, column in _USER_CASCADE_FKS:
        assert f"{model.__tablename__}_{column}_fkey" in text_body


async def test_delete_user_cascades_through_all_child_tables(client):
    """End-to-end: bootstrap a user, attach one row in every cascade
    table, then ``DELETE FROM users`` and assert every child row is
    gone. This is the behaviour ``confirm_transfer`` relies on; the
    previous schema (no DB-side cascade) would have tripped
    ``IntegrityError`` on the first child row."""
    init = signed_init_data(777, "doomed")
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    target_id = resp.json()["id"]

    async with async_session() as session:
        # Notification — the audit-flagged "every new TG user gets a
        # welcome row" case that used to make confirm_transfer fail.
        session.add(
            Notification(
                recipient_id=target_id,
                type=NotificationType.system,
                title="welcome",
                body="hi",
            )
        )
        # Service catalog row.
        from backend.app.models import Category

        cat = (await session.execute(select(Category).limit(1))).scalar_one_or_none()
        if cat is None:
            cat = Category(slug="cascade-test", name="cascade-test", icon="")
            session.add(cat)
            await session.flush()
        session.add(
            Service(
                owner_id=target_id,
                category_id=cat.id,
                title="t",
                description="d",
                status=ServiceStatus.active,
            )
        )
        session.add(Forum(owner_id=target_id, name="f", url="https://t.me/x"))
        session.add(
            Media(
                owner_id=target_id,
                kind="avatar",
                url="/media/avatar.png",
                name="a.png",
            )
        )
        session.add(UserBalance(user_id=target_id, currency_id=1, amount=0, locked=0))
        session.add(
            WalletDeposit(
                user_id=target_id,
                currency_id=1,
                amount=0,
                provider=WalletDepositProvider.cryptobot,
                provider_invoice_id="x-cascade-1",
                status=WalletDepositStatus.pending,
            )
        )
        session.add(
            WalletWithdrawal(
                user_id=target_id,
                currency_id=1,
                amount=0,
                address="addr",
                status=WalletWithdrawStatus.pending,
            )
        )
        await session.commit()

    # Sanity-check we actually attached every child row.
    async with async_session() as session:
        for model, column in _USER_CASCADE_FKS:
            col = model.__table__.columns[column]
            count = (
                await session.execute(select(col).where(col == target_id).limit(1))
            ).scalar_one_or_none()
            assert count is not None, (
                f"Setup failed: no {model.__tablename__} row for target_id={target_id}"
            )

    # The actual cascade test.
    async with async_session() as session:
        await session.execute(delete(User).where(User.id == target_id))
        await session.commit()

    async with async_session() as session:
        for model, column in _USER_CASCADE_FKS:
            col = model.__table__.columns[column]
            leftover = (
                await session.execute(select(col).where(col == target_id).limit(1))
            ).scalar_one_or_none()
            assert leftover is None, (
                f"{model.__tablename__}.{column} did not cascade — row survives"
            )
