"""``/api/support`` — list of admins / arbiters available for DM contact.

The two endpoints expose every user flagged ``is_admin`` or
``is_arbiter`` so the help page can surface them as clickable rows
that open a Telegram DM via ``https://t.me/{username}``.

4.4 — privacy contract for ``SupportPersonOut.user_id``: this field
carries the **Telegram** ``tg_user_id`` (NOT the internal database
id, despite the name). That is **asymmetric** with the equally
public ``UserPublicOut`` (V9 Comments 29/30) which deliberately
omits ``tg_user_id`` — the rationale being that on a profile page
the ``username`` is enough to identify the user without leaking a
numeric Telegram identity. For support contacts the leak is
intentional and documented here so a future maintainer cleaning up
public schemas does NOT remove the field by accident:

  * Audience: every authenticated user (not anonymous).
  * Use case: a future UI may want a fallback deep-link of the form
    ``tg://user?id={tg_user_id}`` for users whose ``username`` is
    empty / has changed; ``https://t.me/{username}`` alone breaks if
    the username is no longer set. The current ``SupportPersonRow``
    component uses only ``username`` so the field is unused on the
    frontend today, but the API contract is stable.
  * Threat model: admins and arbiters are public-facing roles; their
    ``tg_user_id`` is already discoverable via any DM they send. The
    field is NOT a secret; the asymmetry vs ``UserPublicOut`` is the
    only oddity to flag.

If the field IS removed in a future API revision, please also drop
the regression test ``test_support_endpoints_expose_tg_user_id`` in
``tests/test_support_privacy_contract.py`` so it doesn't fail
silently.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from ..deps import CurrentUser, SessionDep
from ..models import User
from ..rate_limit import RLSupport
from ..schemas import SupportPersonOut

router = APIRouter(prefix="/api/support", tags=["support"])


def _person_out(user: User, prefix: str) -> SupportPersonOut:
    # ``user_id`` field carries ``tg_user_id`` by intentional contract;
    # see the module docstring (4.4) for the privacy rationale.
    return SupportPersonOut(
        id=user.id,
        user_id=user.tg_user_id,
        username=user.username or "",
        display_name=user.display_name or (user.username or ""),
        photo_url=user.photo_url,
        admin=1 if user.is_admin else 0,
        prefix=prefix,
    )


@router.get("/admins", response_model=list[SupportPersonOut])
async def list_admins(
    session: SessionDep,
    _user: CurrentUser,
    _rl: RLSupport,
):
    stmt = select(User).where(User.is_admin.is_(True))
    result = await session.execute(stmt)
    return [_person_out(u, "admin") for u in result.scalars().all()]


@router.get("/arbiters", response_model=list[SupportPersonOut])
async def list_arbiters(
    session: SessionDep,
    _user: CurrentUser,
    _rl: RLSupport,
):
    stmt = select(User).where(User.is_arbiter.is_(True))
    result = await session.execute(stmt)
    return [_person_out(u, "arbiter") for u in result.scalars().all()]
