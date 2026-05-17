"""V5-D + V5-E regression suite.

Single file covering every code path the audit's
``audit-status-v10 §2.C/D`` bucket touched.  Each section is anchored
to the audit item id so the failure mode tells you which row of the
backlog has regressed:

* **V5-D-5** — ``selectinload(buyer/seller/currency)`` on
  ``/api/arbitration/deals``.  We don't try to count SQL statements
  (that's flaky against the test DB which truncates between cases);
  instead we drive the endpoint with N concurrent in-arbitration deals
  and assert that the serialised response carries the joined
  ``buyer.username`` / ``seller.username`` / ``currency.code`` for
  every row.  A regression to lazy-loading would either crash on the
  await-after-commit or pop a generic ``MissingGreenlet`` because the
  attribute access happens outside a session.
* **V5-D-7** — categorical CSP-report dampening.  Hit the endpoint
  with a known-noise payload (extension URL) and a known-signal
  payload and assert the log severity differs.  ``caplog`` captures
  both ``INFO`` and ``DEBUG`` so we can read the exact level.
* **V5-D-10** — ``_recompute_user_rating`` collapsed the two
  ``SELECT COUNT(*)`` round-trips into a single
  ``SELECT SUM(CASE ...)``.  Exercise the helper across the full
  rating ladder and assert the counters land exactly where the
  pre-fix per-counter ``COUNT`` queries would have.
* **V5-E-1** — meta-check that the migrations with destructive
  downgrades carry the documented "irreversible data loss" header.
* **V5-E-2 / V5-E-3** — meta-check that the migrations targeted by
  the audit use ``postgresql_concurrently=True`` inside an
  ``autocommit_block`` so ``CREATE INDEX CONCURRENTLY`` is what
  Postgres actually runs.  Mig-2 from the v11 audit asked for the
  same guarantee on the *downgrade* path — the AST walker below
  enforces it per-call so a future migration that creates an index
  concurrently on upgrade but drops it under a plain ``DROP INDEX``
  on downgrade fails the contract, instead of slipping through
  because the file happened to contain a CONCURRENTLY token somewhere
  else.
"""

from __future__ import annotations

import ast
import logging
import pathlib

import pytest
from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import (
    Currency,
    Deal,
    DealStatus,
    PayCommission,
    Review,
    User,
)
from backend.app.services import _recompute_user_rating
from tests.helpers import (
    auth_headers,
    get_user_id_by_tg,
    setup_pin,
    signed_init_data,
)

# ── V5-D-5 ──────────────────────────────────────────────────────────


async def _seed_arbitration_board(client, *, n: int) -> list[int]:
    """Seed ``n`` distinct deals in ``DealStatus.arbitration`` against
    fresh buyer/seller pairs so the arbitration board has multiple
    rows that exercise the ``selectinload`` IN-load.

    Returns the list of deal ids in insertion order.  Each deal has
    its own buyer/seller User row and points at the USDT currency
    seed, so a regression to lazy loading would surface as an
    attribute-after-commit error on the first row that hits the
    ``_deal_out`` projection.
    """
    deal_ids: list[int] = []
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        for i in range(n):
            buyer = User(
                tg_user_id=9_100_000 + i,
                username=f"arb_buyer_{i}",
                display_name="b",
            )
            seller = User(
                tg_user_id=9_200_000 + i,
                username=f"arb_seller_{i}",
                display_name="s",
            )
            session.add_all([buyer, seller])
            await session.flush()
            deal = Deal(
                buyer_id=buyer.id,
                seller_id=seller.id,
                sum=10.0 + i,
                description=f"arb #{i}",
                pay_commission=PayCommission.buyer,
                status=DealStatus.arbitration,
                currency_id=usdt.id,
                amount=10.0 + i,
            )
            session.add(deal)
            await session.flush()
            deal_ids.append(deal.id)
        await session.commit()
    return deal_ids


@pytest.mark.asyncio
async def test_arbitration_list_eager_loads_buyer_seller_currency(client):
    """V5-D-5 — list endpoint serialises every row's buyer / seller /
    currency without an extra round-trip per deal.

    The serializer reads ``deal.buyer.username`` /
    ``deal.seller.username`` / ``deal.currency.code`` for each
    response row.  With the audit fix in place those attributes are
    in-memory by the time ``_deal_out`` runs (selectinload IN-loads
    them in a single follow-up query); without it the access would
    fail at the async-session boundary because the parent ``select``
    has already returned.

    The assertion shape is "every row has the joined fields
    materialised".  That's the empirical signal a regression
    produces: either ``MissingGreenlet`` on access, or a serialiser
    that papered over the missing relationship by returning ``None``
    / ``""``.
    """
    init = signed_init_data(9_001, "arb_admin_lister")
    await setup_pin(client, init)

    async with async_session() as session:
        admin = (await session.execute(select(User).where(User.tg_user_id == 9_001))).scalar_one()
        admin.is_admin = True
        await session.commit()

    await _seed_arbitration_board(client, n=5)

    resp = await client.get("/api/arbitration/deals", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 5, rows
    for r in rows:
        assert r["buyer"].startswith("arb_buyer_"), r
        assert r["seller"].startswith("arb_seller_"), r
        assert r["currency_code"] == "USDT", r


# ── V5-D-7 ──────────────────────────────────────────────────────────


async def test_csp_report_extension_payload_is_dampened_to_debug(client, caplog):
    """V5-D-7 — a CSP violation triggered by a browser-extension
    source URL is bucketed as ``noise`` and logged at ``DEBUG``,
    not the default ``INFO``.

    The body is still preserved verbatim in the log line so an
    operator can grep for the suspect URL — only the level changes.
    """
    payload = (
        b'{"csp-report": {'
        b'"document-uri": "https://example.com/",'
        b'"violated-directive": "script-src",'
        b'"blocked-uri": "chrome-extension://abc/inject.js",'
        b'"source-file": "chrome-extension://abc/inject.js"'
        b"}}"
    )

    with caplog.at_level(logging.DEBUG, logger="backend.app.routers.csp_report"):
        resp = await client.post(
            "/api/csp-report",
            content=payload,
            headers={"Content-Type": "application/csp-report"},
        )
    assert resp.status_code == 204

    records = [r for r in caplog.records if r.name == "backend.app.routers.csp_report"]
    assert records, "csp endpoint must have emitted at least one record"
    # The noise bucket must drop the level below INFO so it doesn't
    # show up in the default-level log pipeline / Sentry stream.
    assert all(r.levelno == logging.DEBUG for r in records), (
        f"extension-noise CSP report must log at DEBUG, got {[r.levelname for r in records]}"
    )
    assert "chrome-extension" in records[-1].getMessage()


async def test_csp_report_real_violation_stays_at_info(client, caplog):
    """V5-D-7 — a "real" CSP violation (no known-noise source) stays
    at ``INFO`` so the regression that originally added the
    ``report-uri`` collector still surfaces in the default-level
    log."""
    payload = (
        b'{"csp-report": {'
        b'"document-uri": "https://example.com/",'
        b'"violated-directive": "script-src",'
        b'"blocked-uri": "https://evil.example/exfil.js",'
        b'"source-file": "https://example.com/app.js"'
        b"}}"
    )

    with caplog.at_level(logging.DEBUG, logger="backend.app.routers.csp_report"):
        resp = await client.post(
            "/api/csp-report",
            content=payload,
            headers={"Content-Type": "application/csp-report"},
        )
    assert resp.status_code == 204

    records = [r for r in caplog.records if r.name == "backend.app.routers.csp_report"]
    assert records, "csp endpoint must have emitted at least one record"
    assert any(r.levelno == logging.INFO for r in records), (
        f"real CSP violation must log at INFO, got {[r.levelname for r in records]}"
    )


async def test_csp_report_unparseable_payload_logs_signal(client, caplog):
    """V5-D-7 — payloads we couldn't JSON-decode err on the side of
    visibility and stay at ``INFO``.  A regression that silently
    dropped unknown shapes into ``DEBUG`` would suppress new browser
    envelopes (e.g. Reporting-API variants) we haven't accounted for
    yet."""
    with caplog.at_level(logging.DEBUG, logger="backend.app.routers.csp_report"):
        resp = await client.post(
            "/api/csp-report",
            content=b"not-json-at-all",
            headers={"Content-Type": "application/csp-report"},
        )
    assert resp.status_code == 204

    records = [r for r in caplog.records if r.name == "backend.app.routers.csp_report"]
    assert records, "csp endpoint must have emitted at least one record"
    assert any(r.levelno == logging.INFO for r in records), (
        f"unparseable CSP report must log at INFO, got {[r.levelname for r in records]}"
    )


async def test_csp_report_reporting_api_batch_all_noise_is_dampened(client, caplog):
    """V5-D-7 — Reporting-API delivers an *array* of records.  A
    batch where every record is noise gets dampened to ``DEBUG``;
    even a single real record in the batch keeps the whole batch at
    ``INFO`` so we don't lose visibility on a mixed delivery.
    """
    all_noise = (
        b"["
        b'{"type": "csp-violation", "body": {'
        b'"blocked-uri": "chrome-extension://aaa/x.js",'
        b'"source-file": "chrome-extension://aaa/x.js"'
        b"}},"
        b'{"type": "csp-violation", "body": {'
        b'"blocked-uri": "moz-extension://bbb/y.js",'
        b'"source-file": "moz-extension://bbb/y.js"'
        b"}}"
        b"]"
    )

    with caplog.at_level(logging.DEBUG, logger="backend.app.routers.csp_report"):
        caplog.clear()
        resp = await client.post(
            "/api/csp-report",
            content=all_noise,
            headers={"Content-Type": "application/reports+json"},
        )
    assert resp.status_code == 204
    records = [r for r in caplog.records if r.name == "backend.app.routers.csp_report"]
    assert records and all(r.levelno == logging.DEBUG for r in records), (
        f"all-noise batch must log at DEBUG, got {[r.levelname for r in records]}"
    )

    mixed = (
        b"["
        b'{"type": "csp-violation", "body": {'
        b'"blocked-uri": "chrome-extension://aaa/x.js"'
        b"}},"
        b'{"type": "csp-violation", "body": {'
        b'"blocked-uri": "https://evil.example/x.js"'
        b"}}"
        b"]"
    )

    with caplog.at_level(logging.DEBUG, logger="backend.app.routers.csp_report"):
        caplog.clear()
        resp = await client.post(
            "/api/csp-report",
            content=mixed,
            headers={"Content-Type": "application/reports+json"},
        )
    assert resp.status_code == 204
    records = [r for r in caplog.records if r.name == "backend.app.routers.csp_report"]
    assert any(r.levelno == logging.INFO for r in records), (
        f"mixed-batch CSP report must log at INFO (at least one real "
        f"violation), got {[r.levelname for r in records]}"
    )


# ── V5-D-10 ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recompute_user_rating_sums_full_ladder(client):
    """V5-D-10 — drive the rating recompute through every star value
    (1..5) at least once and assert the ``good`` / ``bad`` counters
    match the documented rules exactly.

    The audit replaced two sequential ``SELECT COUNT(*)`` queries
    with a single ``SELECT SUM(CASE ...) ``.  A regression in the
    aggregate expression — say, dropping the ``coalesce`` and
    mis-handling the "no reviews" edge case — would surface as
    either ``None`` arithmetic or a count mismatch when no review
    rows exist.  We deliberately exercise both the zero-rows and
    the populated path.
    """
    init = signed_init_data(9_310, "rate_target")
    await setup_pin(client, init)

    async with async_session() as session:
        target_id = await get_user_id_by_tg(session, 9_310)

        # Empty path first: zero reviews must produce
        # ``good=bad=0`` and not crash on ``None`` aggregates.
        target = (await session.execute(select(User).where(User.id == target_id))).scalar_one()
        target.good = 99
        target.bad = 99
        await _recompute_user_rating(session, target)
        await session.flush()
        assert target.good == 0, "no reviews ⇒ good=0"
        assert target.bad == 0, "no reviews ⇒ bad=0"

        # Populated path: 2× rating-5 + 1× rating-4 = 3 good,
        # 1× rating-3 = 0 good and 0 bad (neutral), 2× rating-2 +
        # 1× rating-1 = 3 bad.  Author rows are throwaway — the
        # rating maths is target-side.
        for i, rating in enumerate([5, 5, 4, 3, 2, 2, 1]):
            author = User(
                tg_user_id=9_400_000 + i,
                username=f"rev_author_{i}",
                display_name="a",
            )
            session.add(author)
            await session.flush()
            session.add(
                Review(
                    author_id=author.id,
                    target_id=target_id,
                    deal_id=None,
                    rating=rating,
                    text="",
                )
            )
        await session.commit()

    async with async_session() as session:
        target = (await session.execute(select(User).where(User.id == target_id))).scalar_one()
        await _recompute_user_rating(session, target)
        await session.commit()

    async with async_session() as session:
        target = (await session.execute(select(User).where(User.id == target_id))).scalar_one()
        assert target.good == 3, f"good = ratings 4|5 only; expected 3, got {target.good}"
        assert target.bad == 3, f"bad = ratings 1|2 only; expected 3, got {target.bad}"


# ── V5-E-1 / V5-E-2 / V5-E-3 ───────────────────────────────────────


_ALEMBIC_VERSIONS = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"

_DESTRUCTIVE_DOWNGRADES = (
    "411cbe508b97_drop_legacy_dealstatus_values.py",
    "9f3c1a0b8e21_drop_users_frozen_balance.py",
    "d4f1a8c92e34_drop_user_moderator_flag.py",
    "c8f4a2e91d35_pr_h_audit_refunded_indexes_softdelete.py",
    # H-2 — downgrade narrows Numeric(28,8) money columns back to
    # Numeric(18,8); any value > 10¹⁰ written after the upgrade will
    # fail with ``numeric field overflow`` on downgrade.
    "9c3a4d2e1f08_h2_widen_money_columns_to_28_8.py",
    # H-1 — drops ``users.balance``, the ``invoices`` table and the
    # ``invoicestatus`` enum after backfilling balances into
    # ``user_balances(USDT)``. ``downgrade`` raises immediately;
    # restoring the pre-H-1 state requires a database snapshot.
    "h1a2b3c4d5e6_h1_retire_user_balance_invoice.py",
)

_CONCURRENT_INDEX_MIGRATIONS = (
    "c8f4a2e91d35_pr_h_audit_refunded_indexes_softdelete.py",
    "b8adfad43818_p3_4_fts_search_vector_columns.py",
)


def test_destructive_migrations_document_irreversible_data_loss():
    """V5-E-1 — every migration whose downgrade either drops a
    column or coerces a value bucket back into the catch-all
    pre-fix bucket must carry the standard "irreversible data loss"
    header so an operator running ``alembic downgrade`` against
    production sees the warning in the file header.

    The header text is deliberately a fixed marker (``V5-E-1 —
    irreversible data loss on downgrade``) so this meta-check is a
    simple substring search.  A future migration with a similar
    shape (column drop, enum collapse) should grow the same header
    when it's added; the easiest way to discover that is to keep
    this allow-list-driven test green.
    """
    marker = "V5-E-1 — irreversible data loss on downgrade"
    for filename in _DESTRUCTIVE_DOWNGRADES:
        path = _ALEMBIC_VERSIONS / filename
        text = path.read_text()
        assert marker in text, f"{filename}: missing V5-E-1 irreversible-data-loss header"


def _find_function(module: ast.Module, name: str) -> ast.FunctionDef:
    """Return the top-level ``def {name}(): ...`` node of a migration."""
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"migration is missing a top-level def {name}()")


def _is_op_call(node: ast.AST, attr: str) -> bool:
    """``True`` when ``node`` is an ``op.<attr>(...)`` invocation.

    We deliberately accept *any* ``X.<attr>(...)`` rather than pinning
    on the literal ``op`` symbol so a future ``from alembic import op
    as alembic_op`` rename doesn't silently take the contract off-line.
    """
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attr
    )


def _kwarg_is_true(call: ast.Call, name: str) -> bool:
    """``True`` iff ``call`` passes ``name=True`` as a keyword."""
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant) and kw.value.value is True:
            return True
    return False


def _index_calls(func: ast.FunctionDef, attr: str) -> list[ast.Call]:
    """Collect every ``op.<attr>(...)`` call inside ``func`` (any depth)."""
    return [node for node in ast.walk(func) if _is_op_call(node, attr)]


def test_concurrent_index_migrations_use_autocommit_and_concurrently():
    """V5-E-2 / V5-E-3 / v11 Mig-2 — the migrations the audit flagged
    as table-blocking must run their ``create_index`` *and matching
    ``drop_index``* calls with ``postgresql_concurrently=True``
    inside ``op.get_context().autocommit_block()``.  Without the
    autocommit block Postgres refuses ``CREATE INDEX CONCURRENTLY``
    / ``DROP INDEX CONCURRENTLY``, and without the flag we're still
    on the table-blocking plain form.

    The check is per-call AST inspection rather than a whole-file
    substring match: the audit's Mig-2 callout is specifically that
    a downgrade can quietly regress to a plain ``op.drop_index(...)``
    while the upgrade keeps using CONCURRENTLY, and the file would
    still contain the token from the upgrade path.  Walking the
    ``upgrade()`` / ``downgrade()`` bodies independently forces both
    sides of every index to stay non-blocking.
    """
    for filename in _CONCURRENT_INDEX_MIGRATIONS:
        path = _ALEMBIC_VERSIONS / filename
        text = path.read_text()
        # The autocommit-block guard is module-level — every CONCURRENTLY
        # call must sit inside one, but we don't need to map each call
        # back to a specific ``with`` because the migration apply-time
        # error (``CREATE INDEX CONCURRENTLY cannot run inside a
        # transaction block``) would catch a missing wrapper on the
        # first run.  Substring check is sufficient for the meta-guard.
        assert "autocommit_block" in text, (
            f"{filename}: index ops must be wrapped in "
            f"op.get_context().autocommit_block() so CREATE/DROP INDEX "
            f"CONCURRENTLY is valid"
        )

        module = ast.parse(text, filename=str(path))

        upgrade = _find_function(module, "upgrade")
        create_calls = _index_calls(upgrade, "create_index")
        assert create_calls, (
            f"{filename}: upgrade() declares no op.create_index(...) calls "
            f"but is allow-listed as a CONCURRENTLY index migration"
        )
        for call in create_calls:
            assert _kwarg_is_true(call, "postgresql_concurrently"), (
                f"{filename}:{call.lineno} op.create_index must pass postgresql_concurrently=True"
            )
            assert _kwarg_is_true(call, "if_not_exists"), (
                f"{filename}:{call.lineno} op.create_index must pass "
                f"if_not_exists=True so a retry-driven re-run is idempotent"
            )

        downgrade = _find_function(module, "downgrade")
        drop_calls = _index_calls(downgrade, "drop_index")
        assert drop_calls, (
            f"{filename}: downgrade() declares no op.drop_index(...) calls "
            f"but upgrade() created indexes — the matching DROPs must be "
            f"present so the migration is reversible"
        )
        assert len(drop_calls) >= len(create_calls), (
            f"{filename}: upgrade() creates {len(create_calls)} index/es "
            f"but downgrade() only drops {len(drop_calls)} — the indexes "
            f"would survive a downgrade and conflict with a re-upgrade"
        )
        for call in drop_calls:
            assert _kwarg_is_true(call, "postgresql_concurrently"), (
                f"{filename}:{call.lineno} op.drop_index must pass "
                f"postgresql_concurrently=True (audit Mig-2: downgrade "
                f"must mirror the non-blocking CREATE INDEX CONCURRENTLY)"
            )
            assert _kwarg_is_true(call, "if_exists"), (
                f"{filename}:{call.lineno} op.drop_index must pass "
                f"if_exists=True so a retry-driven re-run is idempotent"
            )
