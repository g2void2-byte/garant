"""Authorization / initData verification."""

from __future__ import annotations

import pytest

from tests.helpers import auth_headers, signed_init_data


async def test_missing_authorization_header(client):
    resp = await client.get("/api/me")
    # Audit (continuation) H-3 — pre-fix this returned 422 from the
    # Pydantic ``missing`` validator because ``authorization`` was a
    # required ``Header()`` parameter. Two problems with that:
    #   1. 422 leaks the internal field name + Pydantic error shape.
    #   2. The frontend re-auth hook is wired on 401/403 so the user
    #      saw a generic "Не удалось" toast instead of a fresh
    #      initData handshake.
    # The header is now optional and ``get_current_user`` returns a
    # clean 401 with the same shape as the other auth failures.
    assert resp.status_code == 401


async def test_invalid_authorization_scheme(client):
    resp = await client.get("/api/me", headers={"Authorization": "Bearer something"})
    assert resp.status_code == 401


async def test_tampered_signature_rejected(client):
    init_data = signed_init_data(100, "alice")
    # Replace the hash field with garbage.
    parts = init_data.rsplit("hash=", 1)
    init_data_bad = parts[0] + "hash=deadbeefdeadbeef"
    resp = await client.get("/api/me", headers=auth_headers(init_data_bad))
    assert resp.status_code == 401


async def test_valid_signature_creates_user(client):
    init_data = signed_init_data(100, "alice")
    resp = await client.get("/api/me", headers=auth_headers(init_data))
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "alice"


@pytest.mark.parametrize("missing_field", ["user", "auth_date"])
async def test_missing_initdata_fields_rejected(client, missing_field):
    init_data = signed_init_data(101, "bob")
    # Drop one of the signed fields; this also invalidates the signature.
    stripped = "&".join(kv for kv in init_data.split("&") if not kv.startswith(f"{missing_field}="))
    resp = await client.get("/api/me", headers=auth_headers(stripped))
    assert resp.status_code == 401
