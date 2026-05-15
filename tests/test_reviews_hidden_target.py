"""R7 / H-12 — ``GET /api/reviews?user=<hidden_user>`` returns 404.

The legacy implementation joined on ``Review.target`` filtered by
``User.username`` only, which leaked review counts for users who'd
flipped ``is_hidden_profile`` (a moderator-grade soft-ban).

Owners still see their own reviews and admins keep full visibility
so a moderator can audit complaints without un-hiding the user.
"""

from __future__ import annotations

from backend.app.db import async_session
from backend.app.models import Review, User
from tests.helpers import auth_headers, signed_init_data


async def _bootstrap(client, *, tg_user_id: int, username: str) -> int:
    init = signed_init_data(tg_user_id, username)
    resp = await client.get("/api/me", headers=auth_headers(init))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _seed_reviews_for(target_id: int, count: int) -> None:
    async with async_session() as session:
        author = User(
            tg_user_id=99001,
            username="r_author",
            display_name="r_author",
        )
        session.add(author)
        await session.flush()
        for i in range(count):
            session.add(
                Review(
                    deal_id=None,
                    author_id=author.id,
                    target_id=target_id,
                    rating=5,
                    text=f"hidden-target-review-{i}",
                )
            )
        await session.commit()


async def test_hidden_target_returns_404_to_outside_caller(client):
    target_id = await _bootstrap(client, tg_user_id=20001, username="hidden_t1")
    async with async_session() as session:
        u = await session.get(User, target_id)
        u.is_hidden_profile = True
        await session.commit()
    await _seed_reviews_for(target_id, 3)

    caller_init = signed_init_data(20002, "outside_caller_1")
    resp = await client.get(
        "/api/reviews",
        params={"user": "hidden_t1"},
        headers=auth_headers(caller_init),
    )
    assert resp.status_code == 404


async def test_hidden_target_returns_own_reviews_to_self(client):
    """The owner of the hidden profile sees their own review feed —
    needed for the profile page to show their own rating."""
    target_id = await _bootstrap(client, tg_user_id=20011, username="hidden_t2")
    async with async_session() as session:
        u = await session.get(User, target_id)
        u.is_hidden_profile = True
        await session.commit()
    await _seed_reviews_for(target_id, 2)

    self_init = signed_init_data(20011, "hidden_t2")
    resp = await client.get(
        "/api/reviews",
        params={"user": "hidden_t2"},
        headers=auth_headers(self_init),
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 2


async def test_hidden_target_returns_reviews_to_admin(client):
    """Admins keep visibility for moderation."""
    target_id = await _bootstrap(client, tg_user_id=20021, username="hidden_t3")
    async with async_session() as session:
        u = await session.get(User, target_id)
        u.is_hidden_profile = True
        await session.commit()
    await _seed_reviews_for(target_id, 1)

    admin_id = await _bootstrap(client, tg_user_id=20022, username="admin_t3")
    async with async_session() as session:
        u = await session.get(User, admin_id)
        u.is_admin = True
        await session.commit()
    admin_init = signed_init_data(20022, "admin_t3")
    resp = await client.get(
        "/api/reviews",
        params={"user": "hidden_t3"},
        headers=auth_headers(admin_init),
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1


async def test_unknown_target_returns_404(client):
    """Sanity: a username that doesn't exist also returns 404 (the
    pre-PR-K branch leaked this as ``200 [] `` which made it
    indistinguishable from a real user with no reviews)."""
    caller_init = signed_init_data(20031, "caller_unknown")
    resp = await client.get(
        "/api/reviews",
        params={"user": "this_user_does_not_exist_anywhere"},
        headers=auth_headers(caller_init),
    )
    assert resp.status_code == 404


async def test_visible_target_still_returns_review_list(client):
    """Regression check: the hidden-profile gate must not affect
    public profiles."""
    target_id = await _bootstrap(client, tg_user_id=20041, username="visible_t1")
    await _seed_reviews_for(target_id, 4)

    caller_init = signed_init_data(20042, "caller_visible_1")
    resp = await client.get(
        "/api/reviews",
        params={"user": "visible_t1"},
        headers=auth_headers(caller_init),
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 4
