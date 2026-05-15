"""Regression tests for the second batch of High-severity follow-ups
from the May review.

* **H4** — the frontend ``dev_init_data`` fallback must be DEV-only.
  Backend has no part in this; the frontend half lives in
  ``frontend/src/lib/tg.ts`` and is verified by ``npm run build`` +
  the literal ``import.meta.env.DEV`` check, which Vite tree-shakes
  out of the production bundle. We pin the contract from this side
  by asserting that the source file contains the guard so a future
  refactor can't silently strip it.
* **H5** — the dead ``User.frozen_balance`` column is gone. The
  ``deposit_min`` filter, the public ``UserOut.deposit`` field, and
  the bot's "Депозит" badge must now read from ``deposit_total``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect

from backend.app.db import async_session
from backend.app.models import User

# --- H4: front-end guard is present in the source. -----------------------


def test_dev_init_data_fallback_is_dev_gated():
    """The localStorage read in ``getInitData`` must be wrapped in
    ``import.meta.env.DEV`` so Vite dead-code-eliminates it from the
    production bundle. If a refactor ever removes the guard, the
    localStorage path comes back in prod (and any XSS / left-over dev
    value bypasses auth when the backend has
    ``allow_unsigned_init_data`` enabled).
    """
    repo_root = Path(__file__).resolve().parents[1]
    src = (repo_root / "frontend" / "src" / "lib" / "tg.ts").read_text()
    # Locate the function body.
    func_start = src.find("export function getInitData")
    assert func_start >= 0, "getInitData() missing from frontend/src/lib/tg.ts"
    func_end = src.find("\n}\n", func_start)
    assert func_end > func_start
    body = src[func_start:func_end]
    assert "dev_init_data" in body, "fallback was removed entirely?"
    # The DEV guard must syntactically dominate the localStorage read.
    guard_pos = body.find("import.meta.env.DEV")
    storage_pos = body.find("localStorage")
    assert guard_pos >= 0, "H4 regression — DEV guard missing"
    assert guard_pos < storage_pos, "H4 regression — DEV guard must precede the localStorage read"


# --- H5: dead column dropped, replacement wired up. ----------------------


def test_user_model_has_no_frozen_balance_attr():
    assert not hasattr(User, "frozen_balance"), (
        "H5 regression — User.frozen_balance came back. The column is "
        "dead and the migration dropped it; if you genuinely need a "
        "frozen-balance field, please write a fresh column rather than "
        "resurrect this one."
    )


@pytest.mark.asyncio
async def test_users_table_no_longer_has_frozen_balance_column():
    """Schema check — the alembic migration must actually have run
    against the test database. Catches the case where the model is
    cleaned up but the migration is missing.
    """
    from backend.app.db import engine

    def _columns(sync_conn):
        return {c["name"] for c in inspect(sync_conn).get_columns("users")}

    async with engine.connect() as conn:
        cols = await conn.run_sync(_columns)
    assert "frozen_balance" not in cols, cols
    assert "deposit_total" in cols, cols


@pytest.mark.asyncio
async def test_deposit_min_filter_uses_deposit_total(client):
    """``GET /api/users?deposit_min=N`` filters by ``deposit_total``
    now. Pre-fix this read ``frozen_balance`` which was always 0 —
    the filter therefore returned no rows in production.
    """
    async with async_session() as session:
        session.add_all(
            [
                User(tg_user_id=9501, username="poor9501", display_name="Poor"),
                User(
                    tg_user_id=9502,
                    username="wealthy9502",
                    display_name="Wealthy",
                    deposit_total=1500,
                ),
            ]
        )
        await session.commit()

    resp = await client.get("/api/users", params={"deposit_min": 500})
    assert resp.status_code == 200, resp.text
    names = {u["username"] for u in resp.json()}
    assert "wealthy9502" in names
    assert "poor9501" not in names


@pytest.mark.asyncio
async def test_user_out_deposit_defaults_to_deposit_total(client):
    """The public ``UserOut.deposit`` field falls back to
    ``deposit_total`` when no per-currency override is passed.
    """
    async with async_session() as session:
        session.add(
            User(
                tg_user_id=9601,
                username="bigfish9601",
                display_name="Big",
                deposit_total=777,
            )
        )
        await session.commit()

    # We hit the public listing endpoint; ``user_to_out`` is invoked
    # without an explicit ``deposit`` override.
    resp = await client.get("/api/users", params={"q": "bigfish9601"})
    assert resp.status_code == 200
    body = resp.json()
    assert body, body
    out = next(u for u in body if u["username"] == "bigfish9601")
    assert out["deposit"] == 777.0


def test_bot_profile_summary_uses_deposit_total():
    """``bot.texts.profile_summary`` reads ``deposit_total`` now.
    A ``SimpleNamespace`` stand-in keeps the test cheap — the
    function only touches attributes, not the ORM.
    """
    from backend.app.bot import texts

    user = SimpleNamespace(
        tg_user_id=42,
        username="alice",
        display_name="Alice",
        is_admin=False,
        is_arbiter=False,
        good=3,
        bad=0,
        deposit_total=250,
    )
    # M-5 — ``profile_summary`` now takes a per-currency breakdown
    # rather than legacy buys_sum/sales_sum scalars. An empty list
    # exercises the same "no completed deals" path the original
    # zero-sum kwargs did.
    body = texts.profile_summary(user, buys_count=0, sales_count=0, by_currency=[])
    # ``_format_money`` renders integer-valued amounts without
    # decimals; the exact format is "$250". The dash sentinel is
    # what we'd see if the function had silently fallen back to a
    # missing attribute.
    assert "$250" in body
    assert "Депозит:</b> —" not in body


def test_alembic_migration_revision_is_registered():
    """The drop migration must be part of the alembic chain so
    fresh databases pick it up. Without this check a renamed file
    would silently fall out of the head.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    repo_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(repo_root / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    revisions = {rev.revision for rev in script.walk_revisions()}
    assert "9f3c1a0b8e21" in revisions, (
        "H5 regression — drop-frozen_balance migration is no longer part of the alembic chain"
    )
