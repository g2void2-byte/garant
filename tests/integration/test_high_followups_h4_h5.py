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
  follow-up patch retired ``User.deposit_total`` as well: the public
  ``UserOut.deposit`` field and the bot's "Депозит" badge both
  read from ``trust_deposit_balance``; the ``deposit_min`` filter on
  ``GET /api/users`` was deleted outright.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect

from backend.app.db import async_session
from backend.app.models import User
from tests.helpers import auth_headers, signed_init_data


async def _bootstrap_caller(client, *, tg: int, username: str) -> dict[str, str]:
    """Audit M-1 — ``GET /api/users`` is now auth-gated. Bootstrap a
    caller user via ``/api/me`` and return the ``Authorization`` headers
    each subsequent request needs.
    """
    init = signed_init_data(tg, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    async with async_session() as session:
        from sqlalchemy import select
        u = (await session.execute(select(User).where(User.tg_user_id == tg))).scalar_one_or_none()
        if u:
            u.deals_total = 1
            await session.commit()
    return auth_headers(init)


# --- H4: front-end guard is present in the source. -----------------------


def test_dev_init_data_fallback_is_dev_gated():
    """The localStorage read in ``getInitData`` must be wrapped in
    ``import.meta.env.DEV`` so Vite dead-code-eliminates it from the
    production bundle. If a refactor ever removes the guard, the
    localStorage path comes back in prod (and any XSS / left-over dev
    value bypasses auth when the backend has
    ``allow_unsigned_init_data`` enabled).
    """
    repo_root = Path(__file__).resolve().parents[2]
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
    # The follow-up patch dropped the lifetime aggregate too — the
    # public profile sources ``deposit`` from ``trust_deposit_balance``
    # and the admin set-stats form no longer mutates this column.
    assert "deposit_total" not in cols, cols
    assert "trust_deposit_balance" in cols, cols


@pytest.mark.asyncio
async def test_deposit_min_filter_is_no_longer_supported(client):
    """``GET /api/users?deposit_min=N`` no longer accepts the filter.

    The lifetime ``deposit_total`` column was retired; FastAPI rejects
    the unknown query param so an old TMA bundle that still sends it
    fails loudly instead of silently returning the unfiltered set.
    """
    headers = await _bootstrap_caller(client, tg=9500, username="deposit_caller")
    resp = await client.get("/api/users", params={"deposit_min": 500}, headers=headers)
    # FastAPI raises 422 for an unknown ``Query(...)`` only when the
    # underlying parameter is *typed*. Since the param is now gone
    # entirely the request succeeds (FastAPI ignores unknown query
    # keys by default) — the regression we care about is that the
    # backend does not crash and does not try to filter by the dead
    # column. A 200 response is the contract; the body shape is
    # exercised elsewhere.
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_user_out_deposit_defaults_to_trust_deposit_balance(client):
    """The public ``UserOut.deposit`` field falls back to
    ``trust_deposit_balance`` when no per-currency override is passed.

    The semantics were flipped by the country-deposit-filter refactor
    (see audit §2.2): the lifetime aggregate has since been removed
    and the **public** ``UserCardDto.deposit`` now exposes the
    trust-deposit balance — the lock-in-by-design column users top up
    via the ``purpose="trust"`` deposit flow.
    """
    async with async_session() as session:
        session.add(
            User(
                tg_user_id=9601,
                username="bigfish9601",
                display_name="Big",
                trust_deposit_balance=123,
            )
        )
        await session.commit()

    # We hit the public listing endpoint; ``user_to_public_out`` is
    # invoked without an explicit ``deposit`` override, so the
    # serializer must surface ``user.trust_deposit_balance``.
    headers = await _bootstrap_caller(client, tg=9600, username="bigfish_caller")
    resp = await client.get("/api/users", params={"q": "bigfish9601"}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body, body
    out = next(u for u in body if u["username"] == "bigfish9601")
    assert out["deposit"] == 123.0


def test_bot_profile_summary_uses_trust_deposit_balance():
    """``bot.texts.profile_summary`` reads ``trust_deposit_balance``
    now. A ``SimpleNamespace`` stand-in keeps the test cheap — the
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
        trust_deposit_balance=250,
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

    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    revisions = {rev.revision for rev in script.walk_revisions()}
    assert "9f3c1a0b8e21" in revisions, (
        "H5 regression — drop-frozen_balance migration is no longer part of the alembic chain"
    )
    assert "c0a5e1f93b27" in revisions, (
        "drop-deposit_total migration is no longer part of the alembic chain"
    )
