"""Regression tests for the audit-fixes-remaining PR.

Covers the LOW / INFO items left open after audit reports #204–#208:

* **§4.15** — ``media.upload_media`` rejects animated GIF / WebP
  payloads with HTTP 415 instead of silently flattening them to the
  first frame.
* **§4.19** — ``POST /api/admin/treasury/{id}/reconcile`` queries
  CryptoBot's ``getTransfers`` API by ``spend_id`` and flips a stuck
  ``pending`` row to ``sent`` from the authoritative source. A
  missing transfer surfaces 404 without mutating the row.
* **§5.5** — ``twofa._warn_fallback_once`` is now backed by a
  ``threading.Lock``-protected state object: concurrent callers see
  exactly one WARNING line and the rest at DEBUG.
* **§15.8** — the legacy DealStatus downgrade emits an explicit
  ``WARNING`` log line about the irreversible data loss carried over
  from the original upgrade.
* **§16.2.1** — the compose file no longer carries a default for
  ``POSTGRES_PASSWORD``; the ``${POSTGRES_PASSWORD:?...}`` token
  fails ``docker compose`` at parse time when unset.
"""

from __future__ import annotations

import io
import logging
import threading
from decimal import Decimal

import pytest
from PIL import Image
from sqlalchemy import select

from backend.app.cryptopay import CryptoPayError, Transfer
from backend.app.db import async_session
from backend.app.models import (
    AdminAuditLog,
    Currency,
    TreasuryWithdrawal,
    User,
)
from backend.app.routers.admin import treasury as treasury_router
from backend.app.routers.admin import twofa as twofa_router
from tests.helpers import auth_headers, setup_pin, signed_init_data, with_totp

# ── shared helpers (copied from sibling tests to avoid coupling) ──


async def _bootstrap(client, *, tg_user_id: int, username: str) -> int:
    init = signed_init_data(tg_user_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


async def _make_admin(client, *, tg: int) -> tuple[str, int]:
    init = signed_init_data(tg, f"admin{tg}")
    uid = await _bootstrap(client, tg_user_id=tg, username=f"admin{tg}")
    async with async_session() as session:
        u = await session.get(User, uid)
        assert u is not None
        u.is_admin = True
        await session.commit()
    return init, uid


def _animated_gif_bytes() -> bytes:
    """Two-frame red→blue GIF."""
    frames = [
        Image.new("P", (4, 4), color=1),
        Image.new("P", (4, 4), color=2),
    ]
    palette = [255, 0, 0, 0, 0, 255] + [0] * (256 * 3 - 6)
    for f in frames:
        f.putpalette(palette)
    buf = io.BytesIO()
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
    )
    return buf.getvalue()


def _animated_webp_bytes() -> bytes:
    """Two-frame red→blue WebP."""
    frames = [
        Image.new("RGBA", (4, 4), color=(255, 0, 0, 255)),
        Image.new("RGBA", (4, 4), color=(0, 0, 255, 255)),
    ]
    buf = io.BytesIO()
    frames[0].save(
        buf,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
    )
    return buf.getvalue()


async def _seed_pending_row(
    *,
    actor_id: int,
    status: str = "pending",
    amount: Decimal = Decimal("1.5"),
    address: str = "98765432",
    cryptobot_transfer_id: str | None = None,
) -> int:
    async with async_session() as session:
        usdt = (await session.execute(select(Currency).where(Currency.code == "USDT"))).scalar_one()
        row = TreasuryWithdrawal(
            actor_id=actor_id,
            currency_id=usdt.id,
            amount=amount,
            address=address,
            status=status,
            note="seed for reconcile test",
            cryptobot_transfer_id=cryptobot_transfer_id,
        )
        session.add(row)
        await session.commit()
        return row.id


# ── §4.15 — animated GIF / WebP rejected ─────────────────────────────────


@pytest.mark.asyncio
async def test_4_15_media_upload_rejects_animated_gif(client):
    """A multi-frame GIF must trip the §4.15 ``is_animated`` gate and
    surface as HTTP 415 with a Russian-language error matching the
    other format rejections.
    """
    init_data = signed_init_data(41501, "anim_gif_uploader")
    await setup_pin(client, init_data)

    resp = await client.post(
        "/api/media/upload",
        data={"kind": "avatar"},
        files={"file": ("anim.gif", _animated_gif_bytes(), "image/gif")},
        headers=auth_headers(init_data),
    )
    assert resp.status_code == 415, resp.text
    assert "Анимир" in resp.text or "animated" in resp.text.lower()


@pytest.mark.asyncio
async def test_4_15_media_upload_rejects_animated_webp(client):
    """Same as the GIF case but exercises the WebP plugin's
    ``n_frames`` path, since Pillow exposes the animation flag
    differently per format.
    """
    init_data = signed_init_data(41502, "anim_webp_uploader")
    await setup_pin(client, init_data)

    resp = await client.post(
        "/api/media/upload",
        data={"kind": "avatar"},
        files={"file": ("anim.webp", _animated_webp_bytes(), "image/webp")},
        headers=auth_headers(init_data),
    )
    assert resp.status_code == 415, resp.text


@pytest.mark.asyncio
async def test_4_15_static_gif_still_accepted(client):
    """Single-frame GIF must continue to work — the §4.15 fix is
    targeted at multi-frame containers, not the format itself.
    """
    from tests.helpers import tiny_image_bytes

    init_data = signed_init_data(41503, "static_gif_uploader")
    await setup_pin(client, init_data)

    resp = await client.post(
        "/api/media/upload",
        data={"kind": "avatar"},
        files={"file": ("static.gif", tiny_image_bytes("GIF"), "image/gif")},
        headers=auth_headers(init_data),
    )
    assert resp.status_code == 201, resp.text


# ── §4.19 — treasury reconcile via CryptoBot getTransfers ─────────────────


class _ReconcileCryptoPay:
    """``CryptoPay`` drop-in for the reconcile path.

    Behaviour is steered by the ``items`` class attribute so each
    test can return a tailored transfer list (matching, mismatched,
    empty) without subclassing.
    """

    items: list[Transfer] = []
    last_kwargs: dict | None = None
    raise_error: CryptoPayError | None = None

    def __init__(self, *_a, **_kw) -> None:
        pass

    async def __aenter__(self) -> _ReconcileCryptoPay:
        return self

    async def __aexit__(self, *_exc) -> None:  # noqa: ANN001
        return None

    async def get_transfers(self, **kwargs) -> list[Transfer]:
        _ReconcileCryptoPay.last_kwargs = kwargs
        if _ReconcileCryptoPay.raise_error is not None:
            raise _ReconcileCryptoPay.raise_error
        return list(_ReconcileCryptoPay.items)

    async def transfer(self, **kwargs):  # pragma: no cover — unused here
        raise AssertionError("reconcile must not call transfer()")


@pytest.fixture
def reconcile_cryptopay(monkeypatch):
    """Wire ``_ReconcileCryptoPay`` into the treasury router and reset
    its scratch state between tests so leaks don't cross-contaminate.
    """
    from backend.app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "cryptobot_token", "real-looking-token")
    monkeypatch.setattr(treasury_router, "CryptoPay", _ReconcileCryptoPay)
    _ReconcileCryptoPay.items = []
    _ReconcileCryptoPay.last_kwargs = None
    _ReconcileCryptoPay.raise_error = None
    yield _ReconcileCryptoPay
    _ReconcileCryptoPay.items = []
    _ReconcileCryptoPay.last_kwargs = None
    _ReconcileCryptoPay.raise_error = None


@pytest.mark.asyncio
async def test_4_19_reconcile_requires_confirm(client, reconcile_cryptopay):
    admin_init, admin_id = await _make_admin(client, tg=41901)
    row_id = await _seed_pending_row(actor_id=admin_id)

    resp = await client.post(
        f"/api/admin/treasury/{row_id}/reconcile",
        json={"confirm": False},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 400, resp.text
    # The reconcile path must short-circuit before reaching CryptoBot.
    assert _ReconcileCryptoPay.last_kwargs is None


@pytest.mark.asyncio
async def test_4_19_reconcile_requires_2fa(client, reconcile_cryptopay):
    admin_init, admin_id = await _make_admin(client, tg=41902)
    row_id = await _seed_pending_row(actor_id=admin_id)

    resp = await client.post(
        f"/api/admin/treasury/{row_id}/reconcile",
        json={"confirm": True},
        headers=auth_headers(admin_init),  # NO with_totp
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_4_19_reconcile_unknown_id_404(client, reconcile_cryptopay):
    admin_init, _ = await _make_admin(client, tg=41903)

    resp = await client.post(
        "/api/admin/treasury/99999999/reconcile",
        json={"confirm": True},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_4_19_reconcile_no_cryptopay_token_503(client, monkeypatch):
    """Without a configured CryptoBot token there's no way to query the
    upstream — fail loud rather than producing a misleading 502.
    """
    from backend.app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "cryptobot_token", "")

    admin_init, admin_id = await _make_admin(client, tg=41904)
    row_id = await _seed_pending_row(actor_id=admin_id)

    resp = await client.post(
        f"/api/admin/treasury/{row_id}/reconcile",
        json={"confirm": True},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 503, resp.text


@pytest.mark.asyncio
async def test_4_19_reconcile_happy_path(client, reconcile_cryptopay):
    """A pending row with a matching transfer on CryptoBot's side
    must flip to ``sent`` with the returned ``transfer_id``, an
    audit row, and a queryable ``treasury.reconcile`` action.
    """
    admin_init, admin_id = await _make_admin(client, tg=41905)
    row_id = await _seed_pending_row(actor_id=admin_id, address="55501234")

    _ReconcileCryptoPay.items = [
        Transfer(
            transfer_id=987_654,
            user_id=55501234,
            asset="USDT",
            amount="1.5",
            status="completed",
            completed_at="2026-05-22T00:00:00Z",
        )
    ]

    resp = await client.post(
        f"/api/admin/treasury/{row_id}/reconcile",
        json={"confirm": True, "note": "auto-sweep"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cryptobot_transfer_id"] == "987654"
    assert body["withdrawal"]["status"] == "sent"
    assert body["withdrawal"]["cryptobot_transfer_id"] == "987654"

    # spend_id contract: ``treas:{row.id}`` — the same key
    # ``treasury_withdraw`` writes in Phase 2.
    assert _ReconcileCryptoPay.last_kwargs == {"spend_id": f"treas:{row_id}"}

    async with async_session() as session:
        row = await session.get(TreasuryWithdrawal, row_id)
        assert row is not None
        assert row.status == "sent"
        assert row.cryptobot_transfer_id == "987654"

        audit = (
            await session.execute(
                select(AdminAuditLog)
                .where(AdminAuditLog.action == "treasury.reconcile")
                .order_by(AdminAuditLog.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        assert audit is not None
        assert audit.actor_id == admin_id
        assert audit.target_id == row_id
        assert audit.target_type == "treasury"
        assert audit.payload is not None
        assert audit.payload.get("spend_id") == f"treas:{row_id}"
        assert audit.payload.get("cryptobot_transfer_id") == "987654"
        assert audit.payload.get("cryptobot_status") == "completed"


@pytest.mark.asyncio
async def test_4_19_reconcile_missing_transfer_returns_404(client, reconcile_cryptopay):
    """No matching transfer on CryptoBot's side → 404, row untouched.

    Crucially we do NOT auto-fail the row: the operator may have
    just hit a temporary blip in CryptoBot's query API, and a
    silent ``failed`` would let the row out of the ``pending``
    accounting bucket prematurely.
    """
    admin_init, admin_id = await _make_admin(client, tg=41906)
    row_id = await _seed_pending_row(actor_id=admin_id)

    # No items returned for this spend_id.
    _ReconcileCryptoPay.items = []

    resp = await client.post(
        f"/api/admin/treasury/{row_id}/reconcile",
        json={"confirm": True},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 404, resp.text

    async with async_session() as session:
        row = await session.get(TreasuryWithdrawal, row_id)
        assert row is not None
        assert row.status == "pending"
        assert row.cryptobot_transfer_id is None

        # No audit row written either — the endpoint must not pollute
        # the log with no-ops, only with state changes.
        action_count = (
            await session.execute(
                select(AdminAuditLog).where(AdminAuditLog.action == "treasury.reconcile")
            )
        ).all()
        assert action_count == []


@pytest.mark.asyncio
async def test_4_19_reconcile_already_sent_is_idempotent(client, reconcile_cryptopay):
    """A row already in ``sent`` returns its existing payload without
    re-querying CryptoBot or writing a duplicate audit row.
    """
    admin_init, admin_id = await _make_admin(client, tg=41907)
    row_id = await _seed_pending_row(
        actor_id=admin_id,
        status="sent",
        cryptobot_transfer_id="prev-123",
    )

    resp = await client.post(
        f"/api/admin/treasury/{row_id}/reconcile",
        json={"confirm": True},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cryptobot_transfer_id"] == "prev-123"
    assert body["withdrawal"]["status"] == "sent"

    # No CryptoBot call — idempotent path.
    assert _ReconcileCryptoPay.last_kwargs is None


@pytest.mark.asyncio
async def test_4_19_reconcile_failed_row_409(client, reconcile_cryptopay):
    """``failed`` is terminal — reconcile should not resurrect it."""
    admin_init, admin_id = await _make_admin(client, tg=41908)
    row_id = await _seed_pending_row(actor_id=admin_id, status="failed")

    resp = await client.post(
        f"/api/admin/treasury/{row_id}/reconcile",
        json={"confirm": True},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_4_19_reconcile_cryptopay_error_propagates_as_502(client, reconcile_cryptopay):
    """An upstream CryptoBot error must not be swallowed — surface as
    502 so the operator knows to retry / investigate.
    """
    admin_init, admin_id = await _make_admin(client, tg=41909)
    row_id = await _seed_pending_row(actor_id=admin_id)

    _ReconcileCryptoPay.raise_error = CryptoPayError("simulated upstream")

    resp = await client.post(
        f"/api/admin/treasury/{row_id}/reconcile",
        json={"confirm": True},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 502, resp.text

    async with async_session() as session:
        row = await session.get(TreasuryWithdrawal, row_id)
        assert row is not None
        assert row.status == "pending"


# ── §5.5 — _fallback_warned is now thread-safe ─────────────────────────────


def test_5_5_fallback_warn_state_is_atomic_under_threads():
    """Spin up 50 threads each calling
    ``_FallbackWarnState.consume_first_observation`` and assert
    *exactly one* returned ``True``.

    Pre-fix the read-modify-write on the bare ``_fallback_warned: bool``
    was unsynchronised; with enough contention multiple threads could
    each observe ``False`` and each emit a WARNING. The lock-protected
    state class collapses the read-modify-write to a single critical
    section.
    """
    state = twofa_router._FallbackWarnState()
    barrier = threading.Barrier(50)
    results: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        observed = state.consume_first_observation()
        with lock:
            results.append(observed)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(1 for r in results if r is True) == 1
    assert sum(1 for r in results if r is False) == 49


def test_5_5_warn_fallback_once_emits_warning_then_debug(caplog):
    """The first call must surface at WARNING; subsequent calls at
    DEBUG. ``_reset_fallback_warn_for_tests`` restores the WARNING
    level so the helper stays testable across runs.
    """
    twofa_router._reset_fallback_warn_for_tests()

    with caplog.at_level(logging.DEBUG, logger=twofa_router.logger.name):
        twofa_router._warn_fallback_once("totp.pending.fallback_write", user_id=1)
        twofa_router._warn_fallback_once("totp.pending.fallback_read", user_id=1)
        twofa_router._warn_fallback_once("totp.pending.fallback_read", user_id=2)

    levels = [
        r.levelno
        for r in caplog.records
        if r.name == twofa_router.logger.name
        and r.message.startswith("admin 2fa: Redis unavailable")
    ]
    assert levels.count(logging.WARNING) == 1
    assert levels.count(logging.DEBUG) == 2

    # After reset, the next call goes back to WARNING.
    caplog.clear()
    twofa_router._reset_fallback_warn_for_tests()
    with caplog.at_level(logging.DEBUG, logger=twofa_router.logger.name):
        twofa_router._warn_fallback_once("totp.pending.fallback_write", user_id=3)
    after_reset = [
        r.levelno
        for r in caplog.records
        if r.name == twofa_router.logger.name
        and r.message.startswith("admin 2fa: Redis unavailable")
    ]
    assert after_reset == [logging.WARNING]


# ── §15.8 — downgrade emits an irreversibility warning ────────────────────


def test_15_8_downgrade_emits_warning_with_log_capture(caplog):
    """The downgrade body must emit an alembic-runtime ``WARNING``
    line about pre-P3.3 rows being unrecoverable, before any DDL
    runs. We stub ``alembic.op.execute`` so the test doesn't need
    an active Alembic context — only the new logging side-effect
    is under test.
    """
    import importlib.util
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    rev_path = repo_root / "alembic" / "versions" / "411cbe508b97_drop_legacy_dealstatus_values.py"
    spec = importlib.util.spec_from_file_location("legacy_rev_411cbe508b97", rev_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)

    # ``op.execute`` requires an active alembic context — stub it so
    # the downgrade body still reaches the WARNING line without
    # actually running DDL against a live DB.
    spec.loader.exec_module(mod)

    executed: list[str] = []

    def _fake_execute(sql: str) -> None:
        executed.append(sql)

    import alembic.op

    original_execute = alembic.op.execute
    alembic.op.execute = _fake_execute  # type: ignore[assignment]
    try:
        with caplog.at_level(logging.WARNING, logger="alembic.runtime.migration"):
            mod.downgrade()
    finally:
        alembic.op.execute = original_execute  # type: ignore[assignment]

    warnings = [
        r
        for r in caplog.records
        if r.name == "alembic.runtime.migration" and "downgrade 411cbe508b97" in r.message
    ]
    assert len(warnings) == 1
    assert "does NOT recover" in warnings[0].message
    assert executed, "downgrade body must have run after the warning"


# ── §16.2.1 — POSTGRES_PASSWORD has no default in compose ─────────────────


def test_16_2_1_compose_has_no_default_postgres_password():
    """The compose file must use ``${POSTGRES_PASSWORD:?...}`` (error
    on unset) rather than ``${POSTGRES_PASSWORD:-garant}`` (silent
    default). A regression would re-introduce the weak-credential
    footgun audit §16.2.1 was opened against.

    We strip ``#``-style comments before scanning so the audit
    rationale in the comment block doesn't trip the regression
    check on its own pre-fix syntax reference.
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    compose_path = repo_root / "docker-compose.yml"

    code_lines = [
        line.split("#", 1)[0] for line in compose_path.read_text(encoding="utf-8").splitlines()
    ]
    code = "\n".join(code_lines)

    # No ``${POSTGRES_PASSWORD:-...}`` default-substitution syntax.
    assert "${POSTGRES_PASSWORD:-" not in code, (
        "docker-compose.yml regressed: re-introduced a default for "
        "POSTGRES_PASSWORD. Audit §16.2.1 requires the ``:?`` "
        "error-on-unset variant so misconfigurations fail loud."
    )
    # The ``:?`` token is used everywhere POSTGRES_PASSWORD is read.
    assert code.count("${POSTGRES_PASSWORD:?") >= 3, (
        "expected POSTGRES_PASSWORD:? in postgres env block + migrate "
        "DSN + backend DSN; one of them is missing the fail-loud guard."
    )


def test_16_2_1_env_example_documents_required_postgres_password():
    """``.env.compose.example`` must surface the new required-secret
    contract so a first-time clone is told to generate a password.
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    example = (repo_root / ".env.compose.example").read_text(encoding="utf-8")

    # Should explicitly mention REQUIRED + the audit ref so a future
    # reader can trace back to the audit history.
    assert "REQUIRED" in example.upper(), example
    assert "§16.2.1" in example, example
    # Default placeholder is gone (no inline secret material).
    assert "garant-dev-please-rotate" not in example, example
