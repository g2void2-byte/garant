"""V9 — privacy / XSS hardening regression suite.

One pricked test per fix in the v9 audit bucket. Each ``async def``
maps to an entry in ``audit-status-v9.md §2.A``:

* Comment 29 — ``UserPublicOut`` (no ``tg_user_id`` leak) on
  ``GET /api/users`` and ``GET /api/users/{username}``.
* Comment 30 — same endpoints also hide ``dm_*`` and
  ``is_banned``/``is_frozen``. Those flags survive on ``/api/me``
  (the requester's own view) and on ``/api/admin/users/{id}``.
* Comment 34 — ``html.escape`` in ``create_broadcast`` so admin-authored
  copy with ``<``/``>``/``&`` doesn't make Telegram reject the message
  as malformed HTML.
* Comment 35 — ``UserUpdate.photo_url`` / ``banner_url`` whitelist:
  ``https://`` and ``/media/...`` only; ``http://`` is dropped.
* Comment 36 — ``ForumOut.url`` whitelist: ``https://`` only;
  ``http://`` and ``tg://`` are both dropped.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from backend.app.db import async_session
from backend.app.models import User
from tests.helpers import auth_headers, signed_init_data, with_totp


async def _bootstrap(client, *, tg_user_id: int, username: str) -> int:
    init = signed_init_data(tg_user_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _make_admin(client, tg: int = 1) -> tuple[str, int]:
    init = signed_init_data(tg, f"admin{tg}")
    uid = await _bootstrap(client, tg_user_id=tg, username=f"admin{tg}")
    async with async_session() as session:
        u = await session.get(User, uid)
        u.is_admin = True
        await session.commit()
    return init, uid


# ── Comment 29 — no tg_user_id on the public user endpoints ─────────────


async def test_public_users_list_omits_tg_user_id(client):
    """``GET /api/users`` must not expose ``user_id`` (which is
    ``tg_user_id``) — that's the privacy leak in Comment 29.

    Pre-fix ``UserOut`` carried ``user_id=tg_user_id`` so any visitor
    could enumerate Telegram IDs by scrolling the user list.
    """
    init_a = signed_init_data(8001, "pub_a")
    init_b = signed_init_data(8002, "pub_b")
    await _bootstrap(client, tg_user_id=8001, username="pub_a")
    await _bootstrap(client, tg_user_id=8002, username="pub_b")

    resp = await client.get("/api/users", headers=auth_headers(init_a))
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) >= 2
    for item in items:
        assert "user_id" not in item, f"user_id leaked: {item}"
        assert "tg_user_id" not in item, f"tg_user_id leaked: {item}"

    # Sanity: the requester's *own* /api/me view still carries it.
    me = await client.get("/api/me", headers=auth_headers(init_b))
    assert me.status_code == 200, me.text
    assert "user_id" in me.json()


async def test_public_user_detail_omits_tg_user_id(client):
    """``GET /api/users/{username}`` mirrors the list endpoint."""
    init = signed_init_data(8003, "pub_detail")
    await _bootstrap(client, tg_user_id=8003, username="pub_detail")

    resp = await client.get(
        "/api/users/pub_detail",
        headers=auth_headers(init),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "user_id" not in body
    assert "tg_user_id" not in body
    # display_name / username are still there — only the tg id is hidden.
    assert body["username"] == "pub_detail"


# ── Comment 30 — no dm_*/is_banned/is_frozen on public endpoints ────────


async def test_public_endpoints_omit_dm_and_moderation_flags(client):
    """``dm_deals``/``dm_deposits``/``dm_system`` and the moderation
    flags (``is_banned``/``is_frozen``) only belong on ``/api/me`` and
    ``AdminUserDetailOut``. The public listing must not leak them.
    """
    init = signed_init_data(8004, "pub_dm")
    await _bootstrap(client, tg_user_id=8004, username="pub_dm")

    list_resp = await client.get("/api/users", headers=auth_headers(init))
    detail_resp = await client.get(
        "/api/users/pub_dm",
        headers=auth_headers(init),
    )
    for resp in (list_resp, detail_resp):
        assert resp.status_code == 200, resp.text
        rows = resp.json() if isinstance(resp.json(), list) else [resp.json()]
        for row in rows:
            for hidden in (
                "dm_deals",
                "dm_deposits",
                "dm_system",
                "is_banned",
                "is_frozen",
            ):
                assert hidden not in row, f"{hidden} leaked: {row}"

    # /api/me still surfaces these flags for the requester themselves.
    me = await client.get("/api/me", headers=auth_headers(init))
    assert me.status_code == 200
    me_body = me.json()
    for present in ("dm_deals", "dm_deposits", "dm_system", "is_banned", "is_frozen"):
        assert present in me_body, f"{present} missing from /api/me"


async def test_admin_user_detail_still_carries_tg_user_id(client):
    """``AdminUserDetailOut`` (``GET /api/admin/users/{id}``) is the
    admin-panel view; ``tg_user_id`` belongs there even after the v9
    public-DTO split. Sanity-check we didn't accidentally hide it
    everywhere.
    """
    admin_init, _admin_uid = await _make_admin(client, tg=8100)
    target_uid = await _bootstrap(client, tg_user_id=8101, username="target")

    resp = await client.get(
        f"/api/admin/users/{target_uid}",
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tg_user_id"] == 8101
    # And ban/freeze flags are still admin-visible.
    assert "is_banned" in body
    assert "is_frozen" in body


# ── Comment 35 — UserUpdate.photo_url/banner_url whitelist ──────────────


async def test_user_update_rejects_http_photo_url(client):
    """``http://`` is no longer in the whitelist; only ``https://`` and
    ``/media/...`` pass. Comment 35.
    """
    init = signed_init_data(8201, "photo_user")
    await _bootstrap(client, tg_user_id=8201, username="photo_user")

    resp = await client.patch(
        "/api/me",
        json={"photo_url": "http://evil.example/avatar.png"},
        headers=auth_headers(init),
    )
    assert resp.status_code == 422, resp.text


async def test_user_update_rejects_http_banner_url(client):
    init = signed_init_data(8202, "banner_user")
    await _bootstrap(client, tg_user_id=8202, username="banner_user")

    resp = await client.patch(
        "/api/me",
        json={"banner_url": "http://evil.example/banner.png"},
        headers=auth_headers(init),
    )
    assert resp.status_code == 422, resp.text


async def test_user_update_accepts_https_and_media_paths(client):
    """``https://...`` and ``/media/...`` continue to pass for both
    avatar and banner.
    """
    init = signed_init_data(8203, "ok_urls")
    await _bootstrap(client, tg_user_id=8203, username="ok_urls")

    ok1 = await client.patch(
        "/api/me",
        json={
            "photo_url": "https://cdn.example/avatar.png",
            "banner_url": "https://cdn.example/banner.png",
        },
        headers=auth_headers(init),
    )
    assert ok1.status_code == 200, ok1.text

    ok2 = await client.patch(
        "/api/me",
        json={
            "photo_url": "/media/avatars/x.png",
            "banner_url": "/media/banners/y.png",
        },
        headers=auth_headers(init),
    )
    assert ok2.status_code == 200, ok2.text


# ── Comment 36 — ForumOut.url whitelist (https:// only) ─────────────────


async def test_forum_url_rejects_http_and_tg_schemes(client):
    """``http://`` and ``tg://`` were both dropped; only ``https://``
    (including ``https://t.me/``) passes. Comment 36.
    """
    init = signed_init_data(8301, "forum_user")
    await _bootstrap(client, tg_user_id=8301, username="forum_user")

    for bad in (
        "http://example.com/thread",
        "tg://resolve?domain=foo",
        "javascript:alert(1)",
    ):
        # Audit (continuation) M-1 — ``name`` now has to come from
        # the whitelist (see ``schemas.FORUM_WHITELIST``). ``Probiv``
        # is one of the approved values; the test still asserts the
        # URL validator rejects the bad scheme.
        resp = await client.patch(
            "/api/me",
            json={"forums": [{"name": "Probiv", "url": bad}]},
            headers=auth_headers(init),
        )
        assert resp.status_code == 422, f"{bad} accepted: {resp.text}"


async def test_forum_url_accepts_https_including_t_me(client):
    init = signed_init_data(8302, "forum_ok")
    await _bootstrap(client, tg_user_id=8302, username="forum_ok")

    # Audit (continuation) M-1 — names sourced from the backend
    # whitelist (lockstep with frontend ``FORUM_OPTIONS``). The
    # URL contract under test (https:// generally + https://t.me/
    # specifically) is unchanged.
    resp = await client.patch(
        "/api/me",
        json={
            "forums": [
                {"name": "Darkmoney", "url": "https://forum.example/board"},
                {"name": "Probiv", "url": "https://t.me/channel"},
            ]
        },
        headers=auth_headers(init),
    )
    assert resp.status_code == 200, resp.text
    forums = resp.json()["forums"]
    assert {f["url"] for f in forums} == {
        "https://forum.example/board",
        "https://t.me/channel",
    }


# ── Comment 34 — html.escape in broadcast DM dispatch ──────────────────


async def test_broadcast_dm_escapes_html_in_title_body_deeplink(client, monkeypatch):
    """The bot is configured with ``parse_mode=HTML``. Unescaped angle
    brackets / ampersands in admin-authored *title/body* copy made
    Telegram reject the message with a 400 ("can't parse entities").
    ``create_broadcast`` ``html.escape``s the title and body before
    splicing them into the ``<b>…</b>`` wrapper.

    M-12 follow-up: the deeplink is now scheme-validated (must start
    with ``https://`` or ``tg://``) and wrapped in an explicit
    ``<a href="…">…</a>`` tag — the previous flat ``html.escape``
    rewrote ``?a=1&b=2`` into ``?a=1&amp;b=2`` *inside* the visible
    text, which Telegram's URL auto-linker refused to recognise.
    """
    import backend.app.routers.admin.broadcasts as broadcasts_mod

    sent_dm = AsyncMock(return_value=True)
    monkeypatch.setattr(broadcasts_mod, "bot_send_dm", sent_dm)

    admin_init, _admin_uid = await _make_admin(client, tg=8400)
    # Recipient: a regular user (audience_role="regular" filters the
    # admin out, so the DM branch only fires for this row).
    await _bootstrap(client, tg_user_id=8401, username="recipient")

    resp = await client.post(
        "/api/admin/broadcasts",
        json={
            "title": "<script>alert(1)</script>",
            "body": "Hello & <welcome> friends",
            "deeplink": "https://t.me/garant?start=deal_42&x=1",
            "dispatch_inapp": False,
            "dispatch_dm": True,
            "audience_role": "regular",
        },
        headers=with_totp(auth_headers(admin_init)),
    )
    assert resp.status_code == 200, resp.text

    # Find the DM addressed to our recipient.
    target_call = next(
        (call for call in sent_dm.await_args_list if call.args and call.args[0] == 8401),
        None,
    )
    assert target_call is not None, sent_dm.await_args_list
    dm_text = target_call.args[1]

    # The literal title/body payload tokens must be escaped — none of
    # these substrings should appear as raw HTML in the outgoing text.
    assert "<script>" not in dm_text
    assert "<welcome>" not in dm_text

    # Title/body entities did make it through.
    assert "&lt;script&gt;" in dm_text
    assert "Hello &amp; &lt;welcome&gt; friends" in dm_text
    # The bold wrapper around the (escaped) title is preserved so
    # Telegram still renders the heading.
    assert dm_text.startswith("<b>&lt;script&gt;alert(1)&lt;/script&gt;</b>")

    # M-12: the deeplink is wrapped in <a href="...">…</a> rather than
    # appended as a flat html-escaped string. The ``href`` attribute
    # value is quote-escaped (``&`` → ``&amp;``) — this is correct HTML
    # and Telegram decodes the entities before opening the link. The
    # visible link text is also escaped for safety.
    assert (
        '<a href="https://t.me/garant?start=deal_42&amp;x=1">'
        "https://t.me/garant?start=deal_42&amp;x=1</a>"
    ) in dm_text


async def test_broadcast_rejects_non_url_deeplink(client):
    """M-12: relative paths / unsupported schemes are now rejected at
    the schema boundary so they never reach the DM dispatch path
    where Telegram's HTML parser would mangle them."""
    admin_init, _admin_uid = await _make_admin(client, tg=8410)
    for bad in [
        "/deals/42?x=<y>&z=1",  # relative path
        "javascript:alert(1)",  # unsafe scheme
        "ftp://example.com",  # unsupported scheme
        "  ",  # whitespace only — should normalise to ``None``? checked below
    ]:
        resp = await client.post(
            "/api/admin/broadcasts",
            json={
                "title": "t",
                "body": "b",
                "deeplink": bad,
                "dispatch_inapp": False,
                "dispatch_dm": True,
                "audience_role": "regular",
            },
            headers=with_totp(auth_headers(admin_init)),
        )
        if bad.strip() == "":
            # Whitespace-only normalises to ``None`` per the existing
            # ``_deeplink_ok`` contract, so the request is accepted.
            assert resp.status_code in (200, 400), resp.text
        else:
            assert resp.status_code == 422, (bad, resp.text)
            assert "https://" in resp.text or "tg://" in resp.text
