from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..deps import CurrentUser, SessionDep
from ..models import Currency, Forum
from ..schemas import UserOut, UserUpdate
from ..serializers import user_to_out

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("", response_model=UserOut)
async def get_me(user: CurrentUser):
    return user_to_out(user)


@router.patch("", response_model=UserOut)
async def update_me(body: UserUpdate, user: CurrentUser, session: SessionDep):
    # V11-L-15 — track which top-level fields the request touched so a
    # JSON-logger pipeline can answer "how often do users flip
    # ``is_hidden_profile``" / "how often is the forums list edited"
    # without parsing the message body. ``UserUpdate`` is a closed
    # Pydantic schema so the field names are fixed-cardinality and safe
    # to index. Free-text values (``display_name``, ``description``,
    # ``photo_url`` …) are deliberately NOT in ``extra``.
    touched: list[str] = []
    if body.display_name is not None:
        user.display_name = body.display_name
        touched.append("display_name")
    if body.description is not None:
        user.description = body.description
        touched.append("description")
    if body.banner_url is not None:
        user.banner_url = body.banner_url or None
        touched.append("banner_url")
    if body.photo_url is not None:
        user.photo_url = body.photo_url or None
        touched.append("photo_url")
    if body.forums is not None:
        # Audit M5 — diff against existing rows instead of
        # delete-all/insert-all so:
        #   * unchanged forums keep their ``Forum.id`` (clients may
        #     cache ids; pre-fix every PATCH rotated them);
        #   * write amplification drops from O(N) DELETE + O(N) INSERT
        #     per PATCH to only the actual changes.
        # The match key is ``(name, url)`` because we treat a renamed
        # forum or a moved URL as a new entry (same as the pre-fix
        # behaviour), keeping the diff intuitive for the user.
        desired = [(fd.name, fd.url) for fd in body.forums]
        desired_set = set(desired)
        kept: set[tuple[str, str]] = set()
        for f in list(user.forums):
            key = (f.name, f.url)
            if key in desired_set and key not in kept:
                kept.add(key)
            else:
                await session.delete(f)
        for key in desired:
            if key not in kept:
                session.add(Forum(owner_id=user.id, name=key[0], url=key[1]))
                # Mark the slot as filled so a duplicate ``(name, url)``
                # inside ``body.forums`` produces a single row rather
                # than two identical entries (which the pre-fix
                # delete-all/insert-all path would happily create).
                kept.add(key)
        touched.append("forums")
    if body.dm_deals is not None:
        user.dm_deals = body.dm_deals
        touched.append("dm_deals")
    if body.dm_deposits is not None:
        user.dm_deposits = body.dm_deposits
        touched.append("dm_deposits")
    if body.dm_system is not None:
        user.dm_system = body.dm_system
        touched.append("dm_system")
    if body.is_anonymous_deals is not None:
        user.is_anonymous_deals = body.is_anonymous_deals
        touched.append("is_anonymous_deals")
    if body.is_hidden_profile is not None:
        user.is_hidden_profile = body.is_hidden_profile
        touched.append("is_hidden_profile")
    if body.country is not None:
        # ``UserUpdate._country_ok`` normalises ``""`` to ``None`` and
        # upper-cases the alpha-2 code; here we just persist whatever
        # the validator returned. ``None`` clears the stored country.
        user.country = body.country
        touched.append("country")
    if body.display_currency_code is not None:
        # Items 13/15 — the validator already normalised the string
        # (uppercased, ASCII, ≤8 chars). Enforce the closed set of
        # *active fiat* currencies here so a malformed wire value or
        # a stale frontend that still ships a crypto code can't strand
        # the user with an unrenderable preference. ``""`` already
        # mapped to ``None`` via the schema validator, which clears the
        # column (UI falls back to USD).
        if body.display_currency_code == "":  # pragma: no cover - validator normalises
            user.display_currency_code = None
        else:
            row = (
                await session.execute(
                    select(Currency).where(
                        Currency.code == body.display_currency_code,
                        Currency.is_active.is_(True),
                        Currency.kind == "fiat",
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                raise HTTPException(
                    400,
                    f"Валюта {body.display_currency_code} недоступна",
                )
            user.display_currency_code = row.code
        touched.append("display_currency_code")
    await session.commit()
    logger.info(
        "me update: user_id=%d fields=%s",
        user.id,
        touched,
        extra={
            "event": "me.update.ok",
            "user_id": user.id,
            "fields": touched,
        },
    )
    # Comment 44 (audit v9): the ``forums`` collection was mutated via
    # ``session.delete`` / ``session.add`` above. ``session.refresh``
    # without ``attribute_names`` does not reload eager relationships,
    # so the cached ``user.forums`` could still reference the just-
    # deleted ``Forum`` rows when the serializer iterates them. Force a
    # selectin reload of just that collection so the response always
    # reflects the post-commit state. All non-relationship columns are
    # kept in memory by ``expire_on_commit=False`` and any
    # ``server_default``s were already filled via SA 2.0 + asyncpg
    # eager-defaults RETURNING on the INSERT path, so no broader
    # ``refresh(user)`` is needed.
    if body.forums is not None:
        await session.refresh(user, attribute_names=["forums"])
    return user_to_out(user)
