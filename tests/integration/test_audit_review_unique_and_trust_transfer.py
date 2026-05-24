"""Regression tests for code-review §1.1 + §2.4 fixes.

§1.1 — ``reviews(author_id, deal_id)`` had no UNIQUE guard, so two
parallel ``POST /api/reviews`` from the same author for the same
deal could both pass the check-then-act SELECT in ``post_review``
and both INSERT. The post-insert ``recompute_user_rating`` then
counted both, doubling ``target.good`` / ``target.bad``. The fix is
a schema-level ``uq_reviews_author_deal`` UNIQUE constraint plus
``IntegrityError → 400/409`` translation in the regular and admin
paths.

§2.4 — ``_has_tradable_data`` (the "target must be a clean shell"
gate in ``confirm_transfer``) did not consider
``User.trust_deposit_balance``. A target with locked-in trust
deposit funds would be ``session.delete``'d during transfer,
silently zeroing the deposit out. The fix adds an explicit
``trust_deposit_balance > 0 → True`` check so the confirm endpoint
rejects with the same "не пустой аккаунт" 400.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.db import async_session
from backend.app.models import Currency, Deal, DealStatus, Review, User
from backend.app.services_account import _has_tradable_data
from tests.helpers import (
    auth_headers,
    signed_init_data,
    with_totp,
)


async def _seed_completed_deal(
    session, buyer_id: int, seller_id: int, *, currency_code: str = "USDT"
) -> int:
    """Create a minimal ``Deal`` row so a ``Review.deal_id`` FK can
    point at something. The status / amount only have to satisfy
    schema NOT NULLs; the unique-constraint tests don't exercise the
    deal state machine itself."""
    cur = (
        await session.execute(select(Currency).where(Currency.code == currency_code))
    ).scalar_one()
    deal = Deal(
        buyer_id=buyer_id,
        seller_id=seller_id,
        status=DealStatus.completed,
        currency_id=cur.id,
        amount=Decimal("1"),
    )
    session.add(deal)
    await session.flush()
    return deal.id


# ── §1.1 — schema-level uniqueness ───────────────────────────────────────


async def test_reviews_unique_constraint_blocks_duplicate_author_deal():
    """Inserting a second ``Review`` with the same ``(author_id,
    deal_id)`` must raise ``IntegrityError`` at flush time."""
    async with async_session() as session:
        author = User(tg_user_id=70001, username="rev_uniq_author")
        target = User(tg_user_id=70002, username="rev_uniq_target")
        session.add_all([author, target])
        await session.flush()
        deal_id = await _seed_completed_deal(session, author.id, target.id)

        first = Review(
            author_id=author.id,
            target_id=target.id,
            deal_id=deal_id,
            rating=5,
            text="first",
        )
        session.add(first)
        await session.flush()

        second = Review(
            author_id=author.id,
            target_id=target.id,
            deal_id=deal_id,
            rating=4,
            text="dup",
        )
        session.add(second)
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_reviews_unique_constraint_allows_null_deal_ids():
    """Postgres treats NULLs as distinct in UNIQUE constraints, so
    historical ``deal_id IS NULL`` rows (produced by the cascade
    ``ondelete=SET NULL`` on ``Deal``) must keep coexisting after the
    constraint is installed. Without this property the migration
    would have to either drop or coalesce every cascade-NULLed
    review."""
    async with async_session() as session:
        author = User(tg_user_id=70011, username="rev_null_author")
        target = User(tg_user_id=70012, username="rev_null_target")
        session.add_all([author, target])
        await session.flush()

        for i in range(3):
            session.add(
                Review(
                    author_id=author.id,
                    target_id=target.id,
                    deal_id=None,
                    rating=5,
                    text=f"null-{i}",
                )
            )
        # Three NULL-deal rows from the same author must commit.
        await session.commit()


async def test_admin_create_review_duplicate_returns_409(client):
    """Two ``POST /api/admin/reviews`` with the same ``(author_id,
    deal_id)`` pair: the second must be rejected with 409 + a clean
    message, not a 500 stack trace from the raw
    ``IntegrityError``."""
    author_init = signed_init_data(70101, "rev_admin_a")
    target_init = signed_init_data(70102, "rev_admin_t")
    a_resp = await client.get("/api/me", headers=auth_headers(author_init))
    t_resp = await client.get("/api/me", headers=auth_headers(target_init))
    a_id = a_resp.json()["id"]
    t_id = t_resp.json()["id"]

    admin_init = signed_init_data(70103, "rev_admin")
    admin_resp = await client.get("/api/me", headers=auth_headers(admin_init))
    admin_id = admin_resp.json()["id"]
    async with async_session() as session:
        admin = await session.get(User, admin_id)
        assert admin is not None
        admin.is_admin = True
        await session.commit()

    async with async_session() as session:
        deal_id = await _seed_completed_deal(session, a_id, t_id)
        await session.commit()

    body = {
        "author_id": a_id,
        "target_id": t_id,
        "deal_id": deal_id,
        "rating": 4,
        "text": "first admin review",
    }
    first = await client.post(
        "/api/admin/reviews",
        json=body,
        headers=with_totp(auth_headers(admin_init)),
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        "/api/admin/reviews",
        json={**body, "text": "dup admin review"},
        headers=with_totp(auth_headers(admin_init)),
    )
    assert second.status_code == 409, second.text

    # The target's ``good`` counter must reflect exactly one review;
    # the second INSERT was rejected before ``recompute_user_rating``
    # could double-count it.
    async with async_session() as session:
        target = await session.get(User, t_id)
        assert target is not None
        assert target.good == 1
        assert target.bad == 0


# ── §2.4 — ``_has_tradable_data`` covers trust_deposit_balance ───────────


async def test_has_tradable_data_flags_nonzero_trust_deposit():
    """A user with ``trust_deposit_balance > 0`` must be treated as
    "not a clean shell" so ``confirm_transfer`` refuses to delete the
    row (which would silently zero the deposit out)."""
    async with async_session() as session:
        u = User(tg_user_id=70201, username="trust_dep_holder")
        u.trust_deposit_balance = Decimal("0.00000001")
        session.add(u)
        await session.commit()
        assert await _has_tradable_data(session, u) is True


async def test_has_tradable_data_clean_when_trust_deposit_zero():
    """A user with zero trust deposit and no other activity is still
    considered an empty shell — otherwise no account transfer would
    ever succeed."""
    async with async_session() as session:
        u = User(tg_user_id=70211, username="trust_dep_empty")
        session.add(u)
        await session.commit()
        assert await _has_tradable_data(session, u) is False
