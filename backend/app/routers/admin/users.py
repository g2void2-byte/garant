"""User management — `/api/admin/users`.

Implements the action set requested in the admin-panel spec:

* Listing with search/filters/sorts.
* Detail view with privileged fields (tg_user_id, IP, login_count).
* State changes:

  - ban / unban
  - freeze / unfreeze
  - reset PIN (clear ``pin_hash``)
  - invalidate sessions (force a fresh PIN entry on next /api/* call —
    in practice rotates the user's effective PIN session via
    :func:`pin.bump_session_version`).
  - set role (``is_admin`` / ``is_arbiter`` / ``is_vip``)
  - set rating override
  - edit aggregate stats (deals_total, good, bad, …)

Every action writes to :class:`AdminAuditLog` and DMs the target user
when applicable (ban, freeze, role change, rating change). All mutations
run inside the same SQL transaction as the audit-row insertion: if the
audit insert fails the whole change is rolled back.

Safety invariants enforced here:

* You can't ban / demote / delete yourself.
* You can't remove the **last** ``is_admin`` user.
* Reason is optional, but if provided is logged into the audit row and
  forwarded to the user's DM.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ... import notifier
from ...admin_audit import log_admin_action, state_change_payload
from ...admin_guard import TotpUser
from ...deps import AdminUser, SessionDep
from ...models import Notification, NotificationType, User
from ...rate_limit import rate_limit
from ...schemas import (
    AdminReasonIn,
    AdminSetRatingIn,
    AdminSetRoleIn,
    AdminSetStatsIn,
    AdminSetTrustDepositIn,
    AdminUserDetailOut,
    AdminUserListItem,
    AdminUserListOut,
)
from ...sql_filters import escape_like_wildcards
from ...ws import manager as ws_manager

# All admin/users/* endpoints share a single 600/min token-bucket. Apply
# at the router level so we don't have to thread an ``RLAdmin`` dep
# through every signature.
router = APIRouter(
    prefix="/api/admin/users",
    tags=["admin"],
    dependencies=[Depends(rate_limit("admin:users", limit=600, window=60))],
)

# --------------------------------------------------------------------- helpers


def _prefix_for(user: User) -> str | None:
    if user.is_admin:
        return "admin"
    if user.is_arbiter:
        return "arbiter"
    if user.is_vip:
        return "vip"
    return None


def _rating_auto(user: User) -> Decimal:
    total = (user.good + user.bad) or 1
    return Decimal(str(round(user.good / total * 5, 1)))


def _to_detail(user: User, *, has_pin: bool) -> AdminUserDetailOut:
    auto = _rating_auto(user)
    manual = Decimal(str(user.rating_manual)) if user.rating_manual is not None else None
    effective = manual if manual is not None else auto
    return AdminUserDetailOut(
        id=user.id,
        tg_user_id=user.tg_user_id,
        username=user.username,
        display_name=user.display_name,
        photo_url=user.photo_url,
        banner_url=user.banner_url,
        description=user.description,
        # Item 12 — "trust deposit" is the public profile's
        # ``deposit`` field. Defensive ``or 0`` mirrors the
        # serializer pattern: in-memory ``User(...)`` rows that
        # tests build without flushing read the attribute as
        # ``None`` until SA applies the column default.
        trust_deposit_balance=Decimal(str(user.trust_deposit_balance or 0)),
        rating_auto=auto,
        rating_manual=manual,
        rating_effective=effective,
        good=user.good,
        bad=user.bad,
        deals_total=user.deals_total,
        deals_success=user.deals_success,
        deals_failed=user.deals_failed,
        deals_arbitrage=user.deals_arbitrage,
        deals_sum_override=Decimal(str(user.deals_sum_override or 0)),
        is_admin=user.is_admin,
        is_arbiter=user.is_arbiter,
        is_vip=user.is_vip,
        is_banned=user.is_banned,
        ban_reason=user.ban_reason,
        is_frozen=user.is_frozen,
        freeze_reason=user.freeze_reason,
        is_anonymous_deals=bool(user.is_anonymous_deals),
        is_hidden_profile=bool(user.is_hidden_profile),
        has_pin=has_pin,
        last_ip=user.last_ip,
        last_login_at=user.last_login_at,
        login_count=user.login_count,
        sessions_count=user.sessions_count or 0,
        created_at=user.created_at,
    )


def _to_list_item(user: User) -> AdminUserListItem:
    return AdminUserListItem(
        id=user.id,
        tg_user_id=user.tg_user_id,
        username=user.username,
        display_name=user.display_name,
        photo_url=user.photo_url,
        prefix=_prefix_for(user),
        is_admin=user.is_admin,
        is_arbiter=user.is_arbiter,
        is_vip=user.is_vip,
        is_banned=user.is_banned,
        is_frozen=user.is_frozen,
        # See ``_to_detail`` for the rationale; the public
        # ``deposit`` field is sourced from ``trust_deposit_balance``.
        trust_deposit_balance=Decimal(str(user.trust_deposit_balance or 0)),
        rating=(
            _rating_auto(user) if user.rating_manual is None else Decimal(str(user.rating_manual))
        ),
        deals_total=user.deals_total,
        deals_success=user.deals_success,
        last_ip=user.last_ip,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


async def _get_user_or_404(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    return user


async def _has_pin(user: User) -> bool:
    return user.pin_hash is not None


async def _ensure_not_self(admin: User, target: User) -> None:
    if admin.id == target.id:
        raise HTTPException(400, "Запрещено выполнять это действие над собой")


async def _ensure_not_last_admin(session: AsyncSession, target: User) -> None:
    """Refuse the operation if ``target`` is the only remaining admin.

    Used by every action that would result in ``is_admin=False`` on a
    user who currently has ``is_admin=True``.

    Audit L-2 — lock every row with ``is_admin=True`` so two parallel
    demote requests can't both observe ``count >= 2`` against the
    same pre-demote snapshot and end up dropping the admin count to
    zero. ``SELECT ... FOR UPDATE`` against the same set serialises
    the demote-second request behind the first one's commit; the
    losing transaction then re-reads the count post-commit and the
    "last admin" check fires correctly. We materialise the rows
    (``.all()``) before measuring length so the lock is taken before
    the count comparison runs.
    """
    if not target.is_admin:
        return
    locked_admin_ids = (
        (await session.execute(select(User.id).where(User.is_admin.is_(True)).with_for_update()))
        .scalars()
        .all()
    )
    if len(locked_admin_ids) <= 1:
        raise HTTPException(400, "Нельзя оставить систему без администраторов")


async def _audit_and_notify(
    *,
    session: AsyncSession,
    request: Request,
    admin: User,
    target: User,
    action: str,
    reason: str | None,
    payload: dict | None,
    dm_title: str | None,
    dm_body: str | None,
) -> None:
    """Shared tail of every state-change action.

    Writes the audit row, inserts the in-app notification, commits, then
    dispatches WS + DM. The audit row and notification row are both
    inserted *before* commit so a Postgres-side constraint violation
    aborts the whole transaction (M-17). WS publish + DM dispatch are
    deferred until *after* commit so a rolled-back transaction never
    leaks an event the user can see (A9-M-1). Going through
    ``notifier`` is the single DM path — the previous ``_dm`` helper
    was removed because it sent a second, HTML-unescaped DM in parallel
    (A9-H-1, A9-M-3).
    """
    await log_admin_action(
        session,
        actor=admin,
        action=action,
        target_type="user",
        target_id=target.id,
        reason=reason,
        payload=payload,
        request=request,
    )
    pending: tuple[Notification, dict | None] | None = None
    if dm_title is not None:
        pending = await notifier.insert(
            session,
            target.id,
            NotificationType.system,
            dm_title,
            dm_body or "",
        )
    await session.commit()
    if pending is not None:
        notif, ws_payload = pending
        try:
            await notifier.dispatch_after_commit(session, notif, ws_payload)
        except (TimeoutError, SQLAlchemyError, OSError, RuntimeError):
            # Audit N-9 — narrowed from ``except Exception``. The
            # commit already landed; transient delivery failures
            # (DB read of the recipient, WS publish, Redis I/O) must
            # not surface as 500 on the admin action. Programming-bug
            # exceptions (``KeyError``/``AttributeError``/...) still
            # propagate so they're visible during development.
            pass


# --------------------------------------------------------------------- listing


@router.get("", response_model=AdminUserListOut)
async def list_users(
    _admin: AdminUser,
    session: SessionDep,
    q: Annotated[str | None, Query(description="search by @username/tg_id")] = None,
    role: Annotated[Literal["admin", "arbiter", "vip", "regular", "any"], Query()] = "any",
    status: Annotated[Literal["any", "active", "banned", "frozen"], Query()] = "any",
    sort: Annotated[
        Literal["created_desc", "created_asc", "rating", "deals"], Query()
    ] = "created_desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminUserListOut:
    stmt = select(User)
    count_stmt = select(func.count()).select_from(User)

    if q:
        q_clean = q.strip().lstrip("@")
        like = f"%{escape_like_wildcards(q_clean.lower())}%"
        conditions = [
            func.lower(User.username).like(like, escape="\\"),
            func.lower(User.display_name).like(like, escape="\\"),
        ]
        if q_clean.isdigit():
            conditions.append(User.tg_user_id == int(q_clean))
        stmt = stmt.where(or_(*conditions))
        count_stmt = count_stmt.where(or_(*conditions))

    role_filter = {
        "admin": User.is_admin.is_(True),
        "arbiter": User.is_arbiter.is_(True),
        "vip": User.is_vip.is_(True),
        "regular": (User.is_admin.is_(False) & User.is_arbiter.is_(False) & User.is_vip.is_(False)),
    }.get(role)
    if role_filter is not None:
        stmt = stmt.where(role_filter)
        count_stmt = count_stmt.where(role_filter)

    status_filter = {
        "active": (User.is_banned.is_(False) & User.is_frozen.is_(False)),
        "banned": User.is_banned.is_(True),
        "frozen": User.is_frozen.is_(True),
    }.get(status)
    if status_filter is not None:
        stmt = stmt.where(status_filter)
        count_stmt = count_stmt.where(status_filter)

    order_clause = {
        "created_desc": User.created_at.desc(),
        "created_asc": User.created_at.asc(),
        "rating": (
            func.coalesce(User.rating_manual, 0).desc(),
            User.good.desc(),
        ),
        "deals": User.deals_total.desc(),
    }[sort]
    if isinstance(order_clause, tuple):
        stmt = stmt.order_by(*order_clause)
    else:
        stmt = stmt.order_by(order_clause)

    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    rows = (await session.execute(stmt)).scalars().all()
    total = int((await session.execute(count_stmt)).scalar_one() or 0)

    return AdminUserListOut(
        items=[_to_list_item(u) for u in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{user_id}", response_model=AdminUserDetailOut)
async def get_user(user_id: int, _admin: AdminUser, session: SessionDep) -> AdminUserDetailOut:
    user = await _get_user_or_404(session, user_id)
    return _to_detail(user, has_pin=await _has_pin(user))


# --------------------------------------------------------------------- actions


@router.post("/{user_id}/ban", response_model=AdminUserDetailOut)
async def ban_user(
    user_id: int,
    body: AdminReasonIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminUserDetailOut:
    target = await _get_user_or_404(session, user_id)
    await _ensure_not_self(admin, target)

    # Idempotent — re-banning a banned user only updates the reason if
    # provided; never writes a duplicate audit row in that case.
    changed = False
    if not target.is_banned:
        target.is_banned = True
        changed = True
    if body.reason is not None and target.ban_reason != body.reason:
        target.ban_reason = body.reason
        changed = True

    if changed:
        await _audit_and_notify(
            session=session,
            request=request,
            admin=admin,
            target=target,
            action="user.ban",
            reason=body.reason,
            payload={"ban_reason": body.reason},
            dm_title="Аккаунт заблокирован",
            dm_body=body.reason or "Обратитесь к администратору для уточнения.",
        )
    return _to_detail(target, has_pin=await _has_pin(target))


@router.post("/{user_id}/unban", response_model=AdminUserDetailOut)
async def unban_user(
    user_id: int,
    body: AdminReasonIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminUserDetailOut:
    target = await _get_user_or_404(session, user_id)

    if target.is_banned:
        target.is_banned = False
        target.ban_reason = None
        await _audit_and_notify(
            session=session,
            request=request,
            admin=admin,
            target=target,
            action="user.unban",
            reason=body.reason,
            payload=None,
            dm_title="Блокировка снята",
            dm_body=body.reason or "Вы снова можете пользоваться платформой.",
        )
    return _to_detail(target, has_pin=await _has_pin(target))


@router.post("/{user_id}/freeze", response_model=AdminUserDetailOut)
async def freeze_user(
    user_id: int,
    body: AdminReasonIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminUserDetailOut:
    target = await _get_user_or_404(session, user_id)
    await _ensure_not_self(admin, target)

    changed = False
    if not target.is_frozen:
        target.is_frozen = True
        changed = True
    if body.reason is not None and target.freeze_reason != body.reason:
        target.freeze_reason = body.reason
        changed = True

    if changed:
        await _audit_and_notify(
            session=session,
            request=request,
            admin=admin,
            target=target,
            action="user.freeze",
            reason=body.reason,
            payload={"freeze_reason": body.reason},
            dm_title="Аккаунт заморожен",
            dm_body=(
                body.reason
                or "Ваш аккаунт временно заморожен. Доступ к сервису закрыт до снятия заморозки."
            ),
        )
    return _to_detail(target, has_pin=await _has_pin(target))


@router.post("/{user_id}/unfreeze", response_model=AdminUserDetailOut)
async def unfreeze_user(
    user_id: int,
    body: AdminReasonIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminUserDetailOut:
    target = await _get_user_or_404(session, user_id)

    if target.is_frozen:
        target.is_frozen = False
        target.freeze_reason = None
        await _audit_and_notify(
            session=session,
            request=request,
            admin=admin,
            target=target,
            action="user.unfreeze",
            reason=body.reason,
            payload=None,
            dm_title="Заморозка снята",
            dm_body=body.reason or "Вы снова можете распоряжаться балансом.",
        )
    return _to_detail(target, has_pin=await _has_pin(target))


@router.post("/{user_id}/reset-pin", response_model=AdminUserDetailOut)
async def reset_pin(
    user_id: int,
    body: AdminReasonIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminUserDetailOut:
    """Force-clear the user's PIN hash and active reset codes.

    The user is required to set a brand-new PIN on next launch.

    Audit H3 — bumping ``pin_session_epoch`` here means any PIN token
    issued before the reset stops decoding to a valid ``(user, epoch)``
    pair on the very next request (see ``deps.require_pin_session``).
    Pre-fix the column was untouched, so a stolen device that had
    captured a fresh PIN-JWT could keep operating against the user's
    account for the rest of that token's TTL — exactly the scenario
    an admin reaches for ``reset-pin`` to defuse. The TOTP epoch is
    deliberately NOT bumped here (the PIN reset is a narrow contract;
    use ``/invalidate-sessions`` when the device itself is suspect
    and the TOTP-gated admin/arbiter session must also die).
    """
    target = await _get_user_or_404(session, user_id)

    if target.pin_hash or target.pin_reset_code_hash:
        target.pin_hash = None
        target.pin_attempts = 0
        target.pin_locked_until = None
        target.pin_reset_code_hash = None
        target.pin_reset_expires = None
        target.pin_session_epoch = (target.pin_session_epoch or 0) + 1
        await _audit_and_notify(
            session=session,
            request=request,
            admin=admin,
            target=target,
            action="user.reset_pin",
            reason=body.reason,
            payload={"pin_session_epoch": int(target.pin_session_epoch)},
            dm_title="PIN сброшен",
            dm_body=body.reason
            or "Администратор сбросил ваш PIN. Установите новый при следующем входе.",
        )
        # Item 8 — bumping ``pin_session_epoch`` revokes future REST
        # calls on the next request, but the client side has no way to
        # know that until something it owns ASKs for a PIN-gated
        # endpoint. The TMA's first request after launch is
        # ``GET /api/me`` (unprotected), so the local PIN-token TTL
        # silently keeps the user in the authenticated tree until the
        # next sensitive call — exactly the scenario the user
        # reported. Push a typed ``pin.reset`` event over WS so the
        # frontend listener (``useLivePinReset``) can drop the local
        # token + invalidate the ``pin/status`` query immediately;
        # ``invalidate_user`` still closes the socket afterwards so a
        # now-untrusted device has to re-auth its WS connection.
        try:
            await ws_manager.publish(
                target.id,
                {"event": "pin.reset", "data": {}},
            )
        except (OSError, RuntimeError):
            # Best-effort: the in-memory enqueue can only fail if the
            # socket state object is mid-close; the focus-refetch
            # fallback in ``usePinStatus`` covers the dropped event.
            pass
        try:
            await ws_manager.invalidate_user(target.id)
        except (OSError, RuntimeError):
            # Best-effort: the manager already swallows individual
            # socket-close failures; only true socket-state errors
            # are expected at this level.
            pass
    return _to_detail(target, has_pin=await _has_pin(target))


@router.post("/{user_id}/invalidate-sessions", response_model=AdminUserDetailOut)
async def invalidate_sessions(
    user_id: int,
    body: AdminReasonIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminUserDetailOut:
    """Revoke all of the target user's active PIN sessions.

    Every PIN token embeds the user's ``pin_session_epoch`` at issue
    time; ``require_pin_session`` compares the claim against the live
    column on every privileged request. Incrementing the column here
    therefore invalidates every token previously issued for this user
    on the next request — no Redis blacklist, no JWT-TTL wait.
    """
    target = await _get_user_or_404(session, user_id)
    target.pin_session_epoch = (target.pin_session_epoch or 0) + 1
    # Bump the TOTP-session epoch in lockstep with the PIN one so the
    # 24h ``X-Totp-Session`` JWT cached on every device the user
    # owned is invalidated by the same admin action. Without this a
    # target who happens to be a fellow admin would keep TOTP-gated
    # write access after invalidate-sessions.
    target.totp_session_epoch = (target.totp_session_epoch or 0) + 1
    await _audit_and_notify(
        session=session,
        request=request,
        admin=admin,
        target=target,
        action="user.invalidate_sessions",
        reason=body.reason,
        payload={
            "pin_session_epoch": int(target.pin_session_epoch),
            "totp_session_epoch": int(target.totp_session_epoch),
        },
        dm_title="Сессия завершена",
        dm_body=body.reason or "Администратор завершил вашу активную сессию. Войдите снова.",
    )
    # Bumping ``pin_session_epoch`` revokes future REST calls on the
    # next request, but a socket that completed first-message auth
    # before the bump keeps streaming notifications. Closing it here
    # forces the now-untrusted device to reconnect and re-auth.
    try:
        await ws_manager.invalidate_user(target.id)
    except (OSError, RuntimeError):
        # Audit N-9 — narrowed from ``except Exception``. WS fan-out
        # is best-effort, but only socket-state errors are expected
        # here (the manager already swallows individual close
        # failures internally). Anything broader is a real bug worth
        # surfacing.
        pass
    return _to_detail(target, has_pin=await _has_pin(target))


@router.post("/{user_id}/role", response_model=AdminUserDetailOut)
async def set_role(
    user_id: int,
    body: AdminSetRoleIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminUserDetailOut:
    """Set the user's role flags atomically.

    Pass ``{is_admin: true}`` to promote; pass all three flags ``false``
    to revoke privileges. The endpoint refuses to:

    * change the caller's own role (prevents self-lockout)
    * remove ``is_admin`` from the last admin in the system
    """
    target = await _get_user_or_404(session, user_id)

    will_change_admin = target.is_admin != body.is_admin
    will_change_arbiter = target.is_arbiter != body.is_arbiter
    will_change_vip = target.is_vip != body.is_vip
    if admin.id == target.id and (will_change_admin or will_change_arbiter or will_change_vip):
        # Self-demotion is the only "self" action that is special-cased
        # because it can lock the caller out. The arbiter / VIP self-flips
        # are also blocked here so an admin cannot grant themselves
        # commission discounts (VIP) or arbitration access without a
        # second admin signing off.
        raise HTTPException(400, "Запрещено менять собственные роли")

    if will_change_admin and not body.is_admin:
        await _ensure_not_last_admin(session, target)

    # Audit M-2 — compare before/after BEFORE touching ``target`` so a
    # future ``await session.commit()`` slipped between the mutation
    # and this guard can't silently land the role flips without an
    # audit row. The previous order (mutate → snapshot → compare →
    # return) only worked because nothing on the no-op path committed,
    # which is a fragile invariant to rely on. This matches the
    # ``set_rating`` shape directly below, which checks first then
    # writes.
    before = {
        "is_admin": target.is_admin,
        "is_arbiter": target.is_arbiter,
        "is_vip": target.is_vip,
    }
    after = {
        "is_admin": body.is_admin,
        "is_arbiter": body.is_arbiter,
        "is_vip": body.is_vip,
    }
    if before == after:
        return _to_detail(target, has_pin=await _has_pin(target))
    target.is_admin = body.is_admin
    target.is_arbiter = body.is_arbiter
    target.is_vip = body.is_vip

    await _audit_and_notify(
        session=session,
        request=request,
        admin=admin,
        target=target,
        action="user.set_role",
        reason=None,
        payload=state_change_payload(before=before, after=after),
        dm_title="Роль обновлена",
        dm_body=_role_change_body(before, after),
    )
    return _to_detail(target, has_pin=await _has_pin(target))


def _role_change_body(before: dict, after: dict) -> str:
    """Human-readable summary of which flags flipped."""
    parts: list[str] = []
    for key, label in [
        ("is_admin", "Администратор"),
        ("is_arbiter", "Арбитр"),
        ("is_vip", "VIP"),
    ]:
        if before.get(key) != after.get(key):
            verb = "выдан" if after.get(key) else "снят"
            parts.append(f"{label}: {verb}")
    return "; ".join(parts) if parts else "Роль не изменена."


@router.post("/{user_id}/rating", response_model=AdminUserDetailOut)
async def set_rating(
    user_id: int,
    body: AdminSetRatingIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminUserDetailOut:
    """Set or clear the manual rating override.

    Reason is **not** required. Passing ``{"rating": null}`` clears the
    override and restores the auto-computed rating.
    """
    target = await _get_user_or_404(session, user_id)
    before = Decimal(str(target.rating_manual)) if target.rating_manual is not None else None
    target.rating_manual = body.rating

    if before == body.rating:
        return _to_detail(target, has_pin=await _has_pin(target))

    await _audit_and_notify(
        session=session,
        request=request,
        admin=admin,
        target=target,
        action="user.set_rating",
        reason=None,
        payload=state_change_payload(
            before={"rating": before},
            after={"rating": body.rating},
        ),
        dm_title="Рейтинг обновлён",
        dm_body=(
            f"Установлен рейтинг {body.rating}"
            if body.rating is not None
            else "Ручной рейтинг сброшен, теперь действует автоматический расчёт."
        ),
    )
    return _to_detail(target, has_pin=await _has_pin(target))


@router.post("/{user_id}/stats", response_model=AdminUserDetailOut)
async def set_stats(
    user_id: int,
    body: AdminSetStatsIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminUserDetailOut:
    """Edit aggregate stats on the user profile.

    Only the keys present in the body are applied — omitted fields stay
    untouched. Negative values are rejected by the Pydantic validator.
    Reason is **not** required per the spec.
    """
    target = await _get_user_or_404(session, user_id)

    before: dict[str, int | float] = {}
    after: dict[str, int | float] = {}

    if body.deals_total is not None and body.deals_total != target.deals_total:
        before["deals_total"] = target.deals_total
        after["deals_total"] = body.deals_total
        target.deals_total = body.deals_total
    if body.deals_success is not None and body.deals_success != target.deals_success:
        before["deals_success"] = target.deals_success
        after["deals_success"] = body.deals_success
        target.deals_success = body.deals_success
    if body.deals_failed is not None and body.deals_failed != target.deals_failed:
        before["deals_failed"] = target.deals_failed
        after["deals_failed"] = body.deals_failed
        target.deals_failed = body.deals_failed
    if body.deals_arbitrage is not None and body.deals_arbitrage != target.deals_arbitrage:
        before["deals_arbitrage"] = target.deals_arbitrage
        after["deals_arbitrage"] = body.deals_arbitrage
        target.deals_arbitrage = body.deals_arbitrage
    if body.good is not None and body.good != target.good:
        before["good"] = target.good
        after["good"] = body.good
        target.good = body.good
    if body.bad is not None and body.bad != target.bad:
        before["bad"] = target.bad
        after["bad"] = body.bad
        target.bad = body.bad
    if body.deals_sum_override is not None:
        current = Decimal(str(target.deals_sum_override or 0))
        if Decimal(str(body.deals_sum_override)) != current:
            before["deals_sum_override"] = str(current)
            after["deals_sum_override"] = str(body.deals_sum_override)
            target.deals_sum_override = Decimal(str(body.deals_sum_override))
    if not after:
        return _to_detail(target, has_pin=await _has_pin(target))

    await _audit_and_notify(
        session=session,
        request=request,
        admin=admin,
        target=target,
        action="user.set_stats",
        reason=None,
        payload=state_change_payload(before=before, after=after),
        dm_title=None,
        dm_body=None,
    )
    return _to_detail(target, has_pin=await _has_pin(target))


@router.post("/{user_id}/trust-deposit", response_model=AdminUserDetailOut)
async def set_trust_deposit(
    user_id: int,
    body: AdminSetTrustDepositIn,
    admin: TotpUser,
    session: SessionDep,
    request: Request,
) -> AdminUserDetailOut:
    """Set the user's trust-deposit balance (absolute value).

    Item 12 — the public profile's ``deposit`` field is sourced from
    :attr:`User.trust_deposit_balance`. The lifetime ``deposit_total``
    aggregate that ``set_stats`` used to write has since been
    removed; this endpoint is the only path that mutates the
    user-visible deposit.

    The body is an *absolute* amount — admin types the new total in
    the form, not a delta. Negative values are rejected at the schema
    layer (the trust balance has no spend / withdraw path so a
    negative state is structurally impossible).
    """
    target = await _get_user_or_404(session, user_id)
    new_value = Decimal(body.amount)
    before = Decimal(str(target.trust_deposit_balance or 0))
    if before == new_value:
        return _to_detail(target, has_pin=await _has_pin(target))
    target.trust_deposit_balance = new_value

    await _audit_and_notify(
        session=session,
        request=request,
        admin=admin,
        target=target,
        action="user.set_trust_deposit",
        reason=body.reason,
        payload=state_change_payload(
            before={"trust_deposit_balance": str(before)},
            after={"trust_deposit_balance": str(new_value)},
        ),
        dm_title="Трастовый депозит обновлён",
        dm_body=f"Новое значение: {new_value} USD",
    )
    return _to_detail(target, has_pin=await _has_pin(target))
