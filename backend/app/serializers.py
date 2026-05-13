"""Shared response serializers.

Centralises ``UserOut`` / similar conversions so individual routers don't
each ship a near-identical ``_user_out`` (and accidentally drift).
"""

from __future__ import annotations

from .models import User
from .schemas import ForumOut, UserOut


def user_to_out(
    user: User,
    *,
    deposit: float | None = None,
    deals_sum: float = 0.0,
) -> UserOut:
    """Convert a :class:`User` ORM row into a :class:`UserOut` DTO.

    ``deposit`` defaults to ``user.frozen_balance`` for backwards compat
    with the old USD column. Pass an explicit value when the caller has
    a per-currency aggregate to surface instead.
    """
    reviews_count = user.good + user.bad
    total = reviews_count or 1
    rating = round(user.good / total * 5, 1)
    if user.is_admin:
        prefix = "admin"
    elif user.is_moderator:
        prefix = "moderator"
    elif user.is_arbiter:
        prefix = "arbiter"
    else:
        prefix = None
    # ``admin`` exposes the user's privilege tier as an int — Continental's
    # search filter sheet uses the same numbering (5=admin, 4=moderator,
    # 3=arbiter, 0=regular).
    if user.is_admin:
        admin_level = 5
    elif user.is_moderator:
        admin_level = 4
    elif user.is_arbiter:
        admin_level = 3
    else:
        admin_level = 0
    return UserOut(
        id=user.id,
        user_id=user.tg_user_id,
        username=user.username or "",
        display_name=user.display_name,
        photo_url=user.photo_url,
        banner_url=user.banner_url,
        balance=float(user.balance),
        deposit=float(deposit if deposit is not None else user.frozen_balance),
        description=user.description,
        prefix=prefix,
        is_admin=user.is_admin,
        is_moderator=user.is_moderator,
        is_arbiter=user.is_arbiter,
        admin=admin_level,
        good=user.good,
        bad=user.bad,
        rating=rating,
        reviews_count=reviews_count,
        deals_count=user.deals_total,
        deals_sum=deals_sum,
        online=True,
        forums=[ForumOut(name=f.name, url=f.url) for f in user.forums],
        dm_deals=bool(user.dm_deals),
        dm_deposits=bool(user.dm_deposits),
        dm_system=bool(user.dm_system),
    )
