"""Regression coverage for user-facing deal-list query validation."""

from __future__ import annotations

from tests.helpers import auth_headers, signed_init_data


async def test_deals_list_rejects_unknown_role_and_status(client):
    """Invalid filters must be typed 422s, not silently ignored.

    Pre-fix ``role=all`` or ``status=wat`` fell through and returned the
    requester's unfiltered deal list, which made frontend/filter typos look
    like valid broad queries.
    """
    init = signed_init_data(51001, "deal_filter_user")

    role_resp = await client.get("/api/deals?role=all", headers=auth_headers(init))
    assert role_resp.status_code == 422, role_resp.text

    status_resp = await client.get("/api/deals?status=wat", headers=auth_headers(init))
    assert status_resp.status_code == 422, status_resp.text
