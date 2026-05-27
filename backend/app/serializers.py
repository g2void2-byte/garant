"""Shared response serializers.

Centralises ``UserOut`` / similar conversions so individual routers don't
each ship a near-identical ``_user_out`` (and accidentally drift).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from .models import User
from .schemas import ForumOut, UserOut, UserPublicOut

_ONLINE_THRESHOLD = timedelta(minutes=5)


def _common_user_fields(
    user: User,
    *,
    deposit: Decimal | None,
    deals_sum: Decimal,
) -> dict:
    """Fields shared between :func:`user_to_out` and :func:`user_to_public_out`.

    ``deals_sum`` defaults to ``Decimal(0)`` upstream; when the
    caller didn't pass an explicit value we fall back to the
    admin-editable ``users.deals_sum_override`` column so the field
    is no longer a hard-coded zero on every endpoint.
    """
    if deals_sum == 0 and getattr(user, "deals_sum_override", None) is not None:
        deals_sum = Decimal(str(user.deals_sum_override or 0))
    reviews_count = user.good + user.bad
    total = reviews_count or 1
    computed_rating = round(user.good / total * 5, 1)
    # Admin PR-A — an admin may override the rating manually; when set
    # we return that value instead of the auto-computed one.
    rating = (
        Decimal(str(user.rating_manual))
        if user.rating_manual is not None
        else Decimal(str(computed_rating))
    )
    # Precedence: admin > arbiter > vip > regular. Admin and VIP can
    # co-exist but admin wins for the *primary* prefix shown next to
    # the username; ``is_vip`` flag is still surfaced separately so
    # the UI can show both badges if needed.
    if user.is_admin:
        prefix = "admin"
    elif user.is_arbiter:
        prefix = "arbiter"
    elif user.is_vip:
        prefix = "vip"
    else:
        prefix = None
    # ``admin`` exposes the user's privilege tier as an int — Continental's
    # search filter sheet uses the same numbering. Tier 4 (moderator) was
    # retired with the role.
    if user.is_admin:
        admin_level = 5
    elif user.is_arbiter:
        admin_level = 3
    elif user.is_vip:
        admin_level = 2
    else:
        admin_level = 0
    # ``deposit`` on the public DTO surfaces the *trust* deposit balance
    # (the lock-in-by-design column). Callers that explicitly pass a
    # per-currency ``deposit`` aggregate still win over the default.
    #
    # ``trust_deposit_balance`` has a Python-side ``default=0`` plus a
    # ``server_default="0"`` on the column, but unit tests that build
    # ``User(...)`` rows in-memory (without flush) see the attribute as
    # ``None`` until SQLAlchemy applies the default — coerce defensively
    # so ``float(None)`` never propagates into the DTO.
    trust_balance = user.trust_deposit_balance if user.trust_deposit_balance is not None else 0
    return dict(
        id=user.id,
        username=user.username or "",
        display_name=user.display_name,
        photo_url=user.photo_url,
        banner_url=user.banner_url,
        deposit=Decimal(str(deposit if deposit is not None else trust_balance)),
        description=user.description,
        prefix=prefix,
        is_admin=user.is_admin,
        is_arbiter=user.is_arbiter,
        is_vip=bool(user.is_vip),
        admin=admin_level,
        good=user.good,
        bad=user.bad,
        rating=rating,
        reviews_count=reviews_count,
        deals_count=user.deals_total,
        # Item 11 — surface the portfolio breakdown on the user
        # DTOs. The columns are already maintained by
        # ``services_deals.resolve_arbitration`` / ``mark_completed``
        # (see ``tests/e2e/test_deals_arbitration.py``); admin panels
        # already read them via ``AdminUserDetailOut``. Defensive
        # ``or 0`` coerce for in-memory ``User(...)`` rows that tests
        # build without flushing — the column has both a Python and a
        # server default so flushed rows are always int.
        deals_success=user.deals_success or 0,
        deals_failed=user.deals_failed or 0,
        deals_arbitrage=user.deals_arbitrage or 0,
        deals_sum=deals_sum,
        online=bool(
            user.last_login_at is not None
            and (datetime.now(UTC) - user.last_login_at.replace(tzinfo=UTC)) < _ONLINE_THRESHOLD
        ),
        forums=[ForumOut(name=f.name, url=f.url) for f in user.forums],
        is_anonymous_deals=bool(user.is_anonymous_deals),
        is_hidden_profile=bool(user.is_hidden_profile),
        country=user.country,
    )


def user_to_out(
    user: User,
    *,
    deposit: Decimal | None = None,
    deals_sum: Decimal = Decimal(0),
) -> UserOut:
    """Convert a :class:`User` ORM row into a :class:`UserOut` DTO.

    Used by ``/api/me`` and ``/api/me`` PATCH: includes ``user_id``
    (= ``tg_user_id``), DM preferences and ban/freeze flags. For the
    public listing endpoints use :func:`user_to_public_out` instead
    (audit v9 Comments 29/30).

    ``deposit`` defaults to ``user.trust_deposit_balance`` — the
    user-visible lock-in deposit. Pass an explicit value when the
    caller has a per-currency aggregate to surface instead.
    """
    base = _common_user_fields(user, deposit=deposit, deals_sum=deals_sum)
    return UserOut(
        **base,
        user_id=user.tg_user_id,
        is_banned=bool(user.is_banned),
        is_frozen=bool(user.is_frozen),
        dm_deals=bool(user.dm_deals),
        dm_deposits=bool(user.dm_deposits),
        dm_system=bool(user.dm_system),
        # Items 13/15 — surface the user's "main" fiat currency
        # preference on ``/api/me`` only; the public DTO doesn't carry
        # it (other users have no reason to see this private setting).
        display_currency_code=user.display_currency_code,
    )


def user_to_public_out(
    user: User,
    *,
    deposit: Decimal | None = None,
    deals_sum: Decimal = Decimal(0),
) -> UserPublicOut:
    """Convert a :class:`User` row into the public :class:`UserPublicOut` DTO.

    Used by ``/api/users`` (list) and ``/api/users/{username}`` (detail).
    Per audit v9 Comments 29/30: omits ``tg_user_id``, DM-preference
    flags, and ``is_banned``/``is_frozen``. The shared logic lives in
    :func:`_common_user_fields` so both serializers stay in sync.
    """
    base = _common_user_fields(user, deposit=deposit, deals_sum=deals_sum)
    return UserPublicOut(**base)
