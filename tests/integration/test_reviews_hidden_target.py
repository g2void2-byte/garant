"""R7 / H-12 — ``GET /api/reviews?user=<hidden_user>`` returns 404.

The legacy implementation joined on ``Review.target`` filtered by
``User.username`` only, which leaked review counts for users who'd
flipped ``is_hidden_profile`` (a moderator-grade soft-ban).

Owners still see their own reviews and admins keep full visibility
so a moderator can audit complaints without un-hiding the user.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from backend.app.db import async_session
from backend.app.models import Currency, Deal, DealStatus, Review, User
from backend.app.time_utils import utcnow
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


async def test_reviews_limit_offset_exposes_total_and_stable_order(client):
    target_id = await _bootstrap(client, tg_user_id=20081, username="reviews_page_target")

    async with async_session() as session:
        author = User(
            tg_user_id=20082,
            username="reviews_page_author",
            display_name="reviews_page_author",
        )
        session.add(author)
        await session.flush()
        now = utcnow()
        reviews = [
            Review(
                deal_id=None,
                author_id=author.id,
                target_id=target_id,
                rating=5,
                text=f"paged-review-{idx}",
                created_at=now,
            )
            for idx in range(4)
        ]
        session.add_all(reviews)
        await session.commit()
        expected_ids = [reviews[2].id, reviews[1].id]

    caller_init = signed_init_data(20083, "reviews_page_viewer")
    resp = await client.get(
        "/api/reviews",
        params={"user": "reviews_page_target", "limit": 2, "offset": 1},
        headers=auth_headers(caller_init),
    )
    assert resp.status_code == 200, resp.text
    assert int(resp.headers["X-Total-Count"]) == 4
    assert [row["id"] for row in resp.json()] == expected_ids


async def test_reviews_deal_id_filter_exposes_only_that_deal(client):
    target_id = await _bootstrap(client, tg_user_id=20091, username="reviews_deal_target")
    author_id = await _bootstrap(client, tg_user_id=20092, username="reviews_deal_author")

    async with async_session() as session:
        currency = (
            await session.execute(select(Currency).where(Currency.code == "USDT"))
        ).scalar_one()
        matching_deal = Deal(
            buyer_id=author_id,
            seller_id=target_id,
            status=DealStatus.completed,
            currency_id=currency.id,
            amount=Decimal("1"),
        )
        other_deal = Deal(
            buyer_id=author_id,
            seller_id=target_id,
            status=DealStatus.completed,
            currency_id=currency.id,
            amount=Decimal("2"),
        )
        session.add_all([matching_deal, other_deal])
        await session.flush()
        matching_review = Review(
            deal_id=matching_deal.id,
            author_id=author_id,
            target_id=target_id,
            rating=5,
            text="matching-deal-review",
        )
        other_review = Review(
            deal_id=other_deal.id,
            author_id=author_id,
            target_id=target_id,
            rating=4,
            text="other-deal-review",
        )
        session.add_all([matching_review, other_review])
        await session.commit()
        expected_id = matching_review.id
        deal_id = matching_deal.id

    caller_init = signed_init_data(20093, "reviews_deal_viewer")
    resp = await client.get(
        "/api/reviews",
        params={"user": "reviews_deal_target", "deal_id": deal_id, "limit": 1},
        headers=auth_headers(caller_init),
    )
    assert resp.status_code == 200, resp.text
    assert int(resp.headers["X-Total-Count"]) == 1
    assert [row["id"] for row in resp.json()] == [expected_id]


# ── V5-D-4 — offset cap on the reviews list ──────────────────────────────


async def test_reviews_offset_above_cap_is_rejected(client):
    """V5-D-4 (M) — ``GET /api/reviews?user=…&offset=10001`` must
    422 at the Pydantic Query validator. Without an upper bound a
    scraper could request ``offset=10_000_000`` and force Postgres
    to walk the full review index just to skip rows we already
    paged past. 10 000 is the cap; anything above is rejected
    before any DB work happens.

    The validator runs before the resolved-target lookup, so the
    request fails even though no user with this username exists —
    that's correct behaviour: refusing 422 on cap violations is the
    cheap, predictable failure mode (an attacker can't probe for
    existence by offset).
    """
    caller_init = signed_init_data(20051, "offset_caller")
    # /api/me bootstrap so the test doesn't accidentally trip auth.
    await client.get("/api/me", headers=auth_headers(caller_init))

    resp = await client.get(
        "/api/reviews",
        params={"user": "anyone", "offset": 10_001},
        headers=auth_headers(caller_init),
    )
    assert resp.status_code == 422, resp.text


async def test_reviews_offset_at_cap_is_allowed(client):
    """Boundary: ``offset=10_000`` is the highest accepted value.
    The user doesn't exist so the router still 404s, but the 422
    validation gate is past — proving the cap is *inclusive*."""
    caller_init = signed_init_data(20061, "offset_caller_2")
    await client.get("/api/me", headers=auth_headers(caller_init))

    resp = await client.get(
        "/api/reviews",
        params={"user": "anyone", "offset": 10_000},
        headers=auth_headers(caller_init),
    )
    # 404 because no user; not 422 because offset is exactly the cap.
    assert resp.status_code == 404, resp.text


async def test_reviews_offset_negative_is_rejected(client):
    """Companion check: negative offsets also 422. Pre-fix the
    endpoint would silently coerce them and return inconsistent
    paging. ``ge=0`` on the Query field is the bound."""
    caller_init = signed_init_data(20071, "offset_caller_3")
    await client.get("/api/me", headers=auth_headers(caller_init))

    resp = await client.get(
        "/api/reviews",
        params={"user": "anyone", "offset": -1},
        headers=auth_headers(caller_init),
    )
    assert resp.status_code == 422, resp.text
