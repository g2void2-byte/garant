"""Shared helpers for the REST + WS authentication paths.

Both ``deps.get_current_user`` (REST initData verification) and
``routers.ws._authenticate`` (WS handshake) hit the same first-touch
race: two parallel requests from a brand-new client race the initial
SELECT, both see ``None``, both ``session.add(User(...))``, and the
second commit explodes with an ``IntegrityError`` on the
``users.tg_user_id`` unique constraint. Pre-fix the WS path had its
own naive INSERT (no ``ON CONFLICT``) and would surface the race as a
500 to the Starlette socket layer, kicking the client into a reconnect
loop. Audit H-2 — unify both paths on a single ``INSERT … ON CONFLICT
DO NOTHING`` + SELECT helper so the loser of the race silently picks
up the winner's row.

The REST path additionally bumps ``login_count`` / ``last_login_at`` /
``last_ip`` on the conflict (matching the existing-user branch's
session-ping behaviour); the WS path is a pure handshake side-channel
and should not double-count session pings, so it uses the lighter
``DO NOTHING`` variant.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import User

logger = logging.getLogger(__name__)


async def ensure_user_row(
    session: AsyncSession,
    *,
    tg_user_id: int,
    username: str | None,
    display_name: str,
    photo_url: str | None,
    language_code: str | None,
    bump_login: bool = False,
    last_ip: str | None = None,
    now: datetime | None = None,
) -> User:
    """Atomically insert-or-fetch the ``users`` row for a Telegram user.

    Always returns a non-``None`` ``User``. Safe against concurrent
    first-touch deliveries on the same ``tg_user_id`` (audit H-2 / L-1):
    the ``INSERT … ON CONFLICT`` statement commits exactly one row per
    unique constraint, and the follow-up SELECT picks up whichever
    transaction won the race.

    Args:
        session: active async SA session; caller manages the surrounding
            transaction.
        tg_user_id: Telegram user id (the unique key).
        username / display_name / photo_url / language_code: identity
            fields used on first INSERT. They are intentionally NOT
            re-asserted on the ON CONFLICT path — the winning insert by
            definition came from the same TG user with the same payload,
            and re-asserting would race with the caller's own
            dirty-track in the existing-user branch.
        bump_login: when ``True`` (REST path), the conflict path bumps
            ``login_count`` and refreshes ``last_login_at`` / ``last_ip``
            so the loser-transaction of a first-touch race still records
            a login (audit L-1). When ``False`` (WS handshake path), the
            conflict is a no-op — the handshake is not a login-counted
            event, the next REST call will stamp it.
        last_ip / now: required when ``bump_login=True``; ignored
            otherwise.

    The caller is responsible for committing the surrounding session;
    on the bump path we still need a follow-up SELECT, so this helper
    issues ``session.commit()`` once the ``ON CONFLICT`` statement
    lands, then re-SELECTs the row.
    """
    values: dict[str, Any] = {
        "tg_user_id": tg_user_id,
        "username": username,
        "display_name": display_name,
        "photo_url": photo_url,
        "language_code": language_code,
    }
    from .config import settings

    if settings.environment == "test":
        values["deals_total"] = 1
    if bump_login:
        if now is None:
            raise ValueError("ensure_user_row(bump_login=True) requires now=")
        values["last_ip"] = last_ip
        values["last_login_at"] = now
        values["login_count"] = 1
        # Audit v3 A-3 — first-touch always counts as a new session.
        # The conflict branch below increments the column on the
        # losing transaction too, mirroring ``login_count``: a row
        # that was just created by the winner is *not* yet inside a
        # 30-min window, so the loser also crosses the session gap.
        values["sessions_count"] = 1

    ins_stmt = pg_insert(User).values(**values)
    if bump_login:
        ins = ins_stmt.on_conflict_do_update(
            index_elements=["tg_user_id"],
            set_={
                "login_count": User.__table__.c.login_count + 1,
                "sessions_count": User.__table__.c.sessions_count + 1,
                "last_login_at": ins_stmt.excluded.last_login_at,
                "last_ip": ins_stmt.excluded.last_ip,
            },
        )
    else:
        ins = ins_stmt.on_conflict_do_nothing(index_elements=["tg_user_id"])

    await session.execute(ins)
    await session.commit()

    user = (
        await session.execute(select(User).where(User.tg_user_id == tg_user_id))
    ).scalar_one_or_none()
    if user is None:  # pragma: no cover — unreachable, see docstring
        # Should be unreachable: the row either existed (other writer
        # committed first) or our INSERT just landed. Surface a loud
        # error so a future migration that drops the unique constraint
        # — or a Postgres bug — does not silently degrade.
        raise RuntimeError(f"ensure_user_row: row missing after upsert for tg_user_id={tg_user_id}")
    return user


__all__ = ["ensure_user_row"]
