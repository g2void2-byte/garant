"""R2 — pin the contract of :class:`backend.app.admin_guard.AdminGuard`.

Three layers:

1. **Unit tests** against the class directly (no FastAPI, no DB) to
   verify the role / TOTP logic in isolation.
2. **Integration tests** through real endpoints, one per variant
   (``AdminUser``, ``TotpUser``, ``AdminOrArbiterUser``), confirming
   that the three module-level singletons exposed via the legacy
   aliases behave the same as the pre-R2 ``require_*`` functions.
3. **Composition test** — verify a non-standard inline guard
   (``AdminGuard(require_totp=True, allow_arbiter=True)``) works
   end-to-end via a temporary route. This pins the inline-use
   pattern that the audit recommends for future endpoints.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.app.admin_guard import (
    ADMIN_GUARD,
    ADMIN_GUARD_OR_ARBITER,
    ADMIN_GUARD_TOTP,
    AdminGuard,
    AdminOrArbiterUser,
    AdminUser,
    TotpUser,
)
from backend.app.db import async_session
from backend.app.models import User
from tests.helpers import auth_headers, signed_init_data, with_totp

# ─── Unit tests ────────────────────────────────────────


def test_singletons_have_expected_flags():
    """The three module-level singletons must match the documented
    permission matrix — that's the contract every router depends on."""
    assert ADMIN_GUARD.require_totp is False
    assert ADMIN_GUARD.allow_arbiter is False
    assert ADMIN_GUARD_TOTP.require_totp is True
    assert ADMIN_GUARD_TOTP.allow_arbiter is False
    assert ADMIN_GUARD_OR_ARBITER.require_totp is False
    assert ADMIN_GUARD_OR_ARBITER.allow_arbiter is True


def test_kwargs_only_constructor():
    """The constructor must reject positional flags — a typo'd
    ``AdminGuard(True)`` should not silently flip ``require_totp``."""
    with pytest.raises(TypeError):
        AdminGuard(True)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        AdminGuard(True, True)  # type: ignore[call-arg]


def test_slots_block_attr_extension():
    """The ``__slots__`` declaration prevents accidental attribute
    bag bloat in long-lived singletons. A new flag must be added to
    ``__slots__`` *and* documented."""
    g = AdminGuard()
    with pytest.raises(AttributeError):
        g.something_new = True  # type: ignore[attr-defined]


# ─── Integration tests ───────────────────────────────


async def _bootstrap(client, *, tg_user_id: int, username: str) -> int:
    init = signed_init_data(tg_user_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _set_roles(uid: int, *, admin=False, arbiter=False) -> None:
    async with async_session() as session:
        u = await session.get(User, uid)
        u.is_admin = admin
        u.is_arbiter = arbiter
        await session.commit()


async def test_admin_user_alias_admin_route_rbac(client):
    """``AdminUser`` (no TOTP, no arbiter) must reject non-admins."""
    # Non-admin caller -> 403.
    init = signed_init_data(7001, "guard_alice")
    await _bootstrap(client, tg_user_id=7001, username="guard_alice")
    resp = await client.get("/api/admin/users", headers=auth_headers(init))
    assert resp.status_code == 403

    # Promote -> 200.
    init2 = signed_init_data(7002, "guard_admin")
    uid = await _bootstrap(client, tg_user_id=7002, username="guard_admin")
    await _set_roles(uid, admin=True)
    resp = await client.get("/api/admin/users", headers=auth_headers(init2))
    assert resp.status_code == 200, resp.text


async def test_totp_user_alias_requires_admin_and_totp(client):
    """``TotpUser`` requires admin AND a valid TOTP header. Verify
    both gates fire and the order — role first, then TOTP — by
    checking that a non-admin bounces with 403 even with the bypass
    header attached."""
    init = signed_init_data(7011, "totp_alice")
    await _bootstrap(client, tg_user_id=7011, username="totp_alice")

    # Non-admin + valid bypass -> still 403 (role gate fires first).
    resp = await client.put(
        "/api/admin/categories",
        json={"slug": "guard-1", "name": "x", "icon": "x"},
        headers=with_totp(auth_headers(init)),
    )
    assert resp.status_code == 403

    # Admin + no TOTP header -> 401.
    init2 = signed_init_data(7012, "totp_admin")
    uid = await _bootstrap(client, tg_user_id=7012, username="totp_admin")
    await _set_roles(uid, admin=True)
    resp = await client.put(
        "/api/admin/categories",
        json={"slug": "guard-2", "name": "x", "icon": "x"},
        headers=auth_headers(init2),
    )
    assert resp.status_code in (401, 403)

    # Admin + valid bypass -> 200.
    resp = await client.put(
        "/api/admin/categories",
        json={"slug": "guard-3", "name": "x", "icon": "x"},
        headers=with_totp(auth_headers(init2)),
    )
    assert resp.status_code == 200, resp.text


async def test_admin_or_arbiter_alias(client):
    """``AdminOrArbiterUser`` accepts admins AND arbiters but
    rejects plain users."""
    # Plain user -> 403.
    init = signed_init_data(7021, "arb_alice")
    await _bootstrap(client, tg_user_id=7021, username="arb_alice")
    resp = await client.get("/api/admin/arbitration", headers=auth_headers(init))
    assert resp.status_code == 403

    # Arbiter -> 200.
    init2 = signed_init_data(7022, "arb_user")
    uid = await _bootstrap(client, tg_user_id=7022, username="arb_user")
    await _set_roles(uid, arbiter=True)
    resp = await client.get("/api/admin/arbitration", headers=auth_headers(init2))
    assert resp.status_code == 200, resp.text


# ─── Composition test ─────────────────────────────────


async def test_inline_guard_with_totp_and_arbiter(monkeypatch):
    """An inline ``AdminGuard(require_totp=True, allow_arbiter=True)``
    declared in a fresh app must enforce **both** gates: arbiter-or-
    admin AND a valid TOTP code. Pins the composition pattern the
    docstring advertises so future endpoints can rely on it without
    a regression sneaking in."""

    # Side-load only the pieces we need to spin up a tiny ASGI app —
    # this keeps the test independent of the main app's middleware
    # stack and rate-limiters so we can hit the same endpoint many
    # times in quick succession.
    from backend.app.deps import get_current_user
    from backend.app.main import app as main_app

    app = FastAPI()

    @app.get("/probe")
    async def probe(
        u: User = Depends(AdminGuard(require_totp=True, allow_arbiter=True)),
    ):
        return {"id": u.id, "username": u.username}

    # Re-use the main app's dependency overrides so the same Telegram
    # initData / TOTP bypass logic runs.
    app.dependency_overrides = main_app.dependency_overrides.copy()
    # ``get_current_user`` still needs the DB; bind the session
    # dependency from the main app so we don't double-open pools.
    for k, v in main_app.dependency_overrides.items():
        if k is get_current_user:
            app.dependency_overrides[k] = v

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Seed a plain user, an arbiter and an admin via the main app.
        async with async_session() as session:
            for tg, uname, role in (
                (7031, "comp_alice", None),
                (7032, "comp_arb", "arbiter"),
                (7033, "comp_admin", "admin"),
            ):
                row = (
                    await session.execute(select(User).where(User.tg_user_id == tg))
                ).scalar_one_or_none()
                if row is None:
                    row = User(tg_user_id=tg, username=uname, display_name=uname)
                    session.add(row)
                    await session.flush()
                if role == "arbiter":
                    row.is_arbiter = True
                elif role == "admin":
                    row.is_admin = True
            await session.commit()

        # Plain user — role gate -> 403.
        plain = signed_init_data(7031, "comp_alice")
        resp = await ac.get("/probe", headers=with_totp(auth_headers(plain)))
        assert resp.status_code == 403, resp.text

        # Arbiter — role gate passes, TOTP bypass attached -> 200.
        arb = signed_init_data(7032, "comp_arb")
        resp = await ac.get("/probe", headers=with_totp(auth_headers(arb)))
        assert resp.status_code == 200, resp.text

        # Arbiter without TOTP header -> 401 (TOTP gate fires).
        resp = await ac.get("/probe", headers=auth_headers(arb))
        assert resp.status_code in (401, 403)


# ─── Type aliases sanity ─────────────────────────────


def test_aliases_are_distinct():
    """The three aliases must be three different ``Depends(...)``
    declarations so FastAPI can cache them separately."""
    # The Annotated types resolve to a tuple ``(User, Depends(...))``.
    # We can't compare deps directly (different singletons), but we
    # can confirm they all wrap a Depends() and that the underlying
    # ``dependency`` attribute differs between the three.
    from typing import get_args

    a_admin = get_args(AdminUser)
    a_totp = get_args(TotpUser)
    a_arb = get_args(AdminOrArbiterUser)
    # User as the base type:
    assert a_admin[0] is User
    assert a_totp[0] is User
    assert a_arb[0] is User
    # Depends(...) wrappers must wrap three different singletons:
    assert a_admin[1].dependency is ADMIN_GUARD
    assert a_totp[1].dependency is ADMIN_GUARD_TOTP
    assert a_arb[1].dependency is ADMIN_GUARD_OR_ARBITER
