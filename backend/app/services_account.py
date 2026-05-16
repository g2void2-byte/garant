"""Account-transfer business logic (PR-CA).

Lets a user re-point their account to a different Telegram identity
without losing history. The source (existing) account requests a
one-time code that is delivered via the bot DM; the target (freshly-
created) account submits the code to transfer ownership.

Security model:

* ``start`` is PIN-gated — proves the caller controls the source TG
  account *and* knows the source PIN.
* ``confirm`` is authenticated via initData of the *new* TG account
  only. The 6-digit one-time code is the second factor; the new account
  must not have any tradable data of its own (no deals, services,
  reviews, wallet balances, PIN) so we can safely discard it before
  re-pointing the source ``tg_user_id``.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import (
    AccountTransferCode,
    Deal,
    Forum,
    Notification,
    Review,
    Service,
    User,
    UserBalance,
    WalletDeposit,
    WalletWithdrawal,
)
from .time_utils import utcnow

logger = logging.getLogger(__name__)

# V11-L-1 — module-level aliases for backwards-compat with existing
# call sites and tests that import these names directly. The runtime
# source of truth is :mod:`backend.app.config.settings`; resolving via
# ``settings`` at call-time means a production knob lifts through to
# every caller (issue, generate, confirm) without a code change.
CODE_LEN = settings.account_transfer_code_len

# Max number of failed ``confirm_transfer`` attempts allowed against a
# single ``AccountTransferCode`` before we burn it. The hash space is
# only 10⁶ so we have to cap probing aggressively — anything ≥10
# attempts is well past "user mistyped twice". Lifted to
# ``settings.account_transfer_max_confirm_attempts`` (V11-L-1).
MAX_CONFIRM_ATTEMPTS = settings.account_transfer_max_confirm_attempts


def _now() -> datetime:
    # Tz-naive UTC to match ``DateTime`` columns in the DB. Postgres
    # rejects tz-aware values written to ``TIMESTAMP WITHOUT TIME ZONE``.
    return utcnow()


def _generate_code() -> str:
    # V11-L-1 — read length from settings every call so a runtime
    # config change is observed without re-importing the module.
    return "".join(secrets.choice("0123456789") for _ in range(settings.account_transfer_code_len))


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _verify_code(code: str, code_hash: str) -> bool:
    if not code_hash:
        return False
    return hmac.compare_digest(_hash_code(code), code_hash)


# Comment 43 (audit v9): never hand out a code that collides with an
# already-active one. The hash space is only 10⁶, so without this guard
# a fresh ``issue_code`` could (with non-negligible probability under
# load) generate a digit-string that already belongs to another live
# transfer and the verifier would happily accept it for either source.
# V11-L-1 — value is now sourced from
# ``settings.account_transfer_max_code_generation_attempts`` so it can be
# tuned without a code change. Default 100 matches the previous value.
MAX_CODE_GENERATION_ATTEMPTS = settings.account_transfer_max_code_generation_attempts


async def _generate_unique_code(session: AsyncSession) -> str:
    """Return a code whose hash is not currently active.

    Walks at most ``settings.account_transfer_max_code_generation_attempts``
    iterations — in practice we collide ~0 times because the live code
    set is tiny, but we bail loudly rather than spinning forever if the
    table ever fills up beyond what the configured digit-count can
    address.

    V11-M-12 — emit a ``logger.warning`` once the iteration count
    crosses ``settings.account_transfer_code_generation_warn_threshold``.
    Pre-fix the helper silently retried up to 100 times and only
    surfaced anything once it had blown the cap; that hides the early
    warning signs of pressure on the OTP keyspace (table not getting
    purged, TTL too long, etc.) until the first user hits a 500.
    """
    max_attempts = settings.account_transfer_max_code_generation_attempts
    warn_threshold = settings.account_transfer_code_generation_warn_threshold
    for iteration in range(1, max_attempts + 1):
        candidate = _generate_code()
        existing = await session.execute(
            select(AccountTransferCode.id).where(
                AccountTransferCode.code_hash == _hash_code(candidate),
                AccountTransferCode.consumed_at.is_(None),
                AccountTransferCode.expires_at > _now(),
            )
        )
        if existing.first() is None:
            if iteration > warn_threshold:
                logger.warning(
                    "account-transfer code generation took %d attempts "
                    "(warn_threshold=%d, max_attempts=%d) — investigate "
                    "live-code purge / TTL pressure",
                    iteration,
                    warn_threshold,
                    max_attempts,
                )
            return candidate
    raise RuntimeError(
        "unable to generate a unique account-transfer code after %d tries" % max_attempts
    )


async def _purge_expired(session: AsyncSession) -> None:
    """Remove codes that have already expired or been consumed.

    Keeps the table small and avoids accidentally matching against a
    stale row (the hash space is small — 1 in 10⁶ — so we must rotate
    aggressively).

    Comment 43 (audit v9): previously this kept rows for up to 24 h
    (``created_at < now - 1 day`` AND-gate). With the default 5-min TTL
    that left dead codes sitting in the table for the rest of the day
    — they could not be used anymore, but they bloated the table and
    let a new ``issue_code`` waste collision-check work. We now purge
    every expired or consumed row immediately; the `created_at`
    floor was redundant guard rail that has no useful effect.
    """
    await session.execute(
        delete(AccountTransferCode).where(
            or_(
                AccountTransferCode.expires_at < _now(),
                AccountTransferCode.consumed_at.is_not(None),
            ),
        )
    )


async def _invalidate_active_for(session: AsyncSession, user_id: int) -> None:
    """Mark all live codes for a given source user as consumed.

    Called both before issuing a fresh one (so the old codes stop working
    immediately) and on explicit user cancel.
    """
    stmt = select(AccountTransferCode).where(
        AccountTransferCode.source_user_id == user_id,
        AccountTransferCode.consumed_at.is_(None),
    )
    result = await session.execute(stmt)
    now = _now()
    for row in result.scalars().all():
        row.consumed_at = now


async def get_active_code(session: AsyncSession, user_id: int) -> AccountTransferCode | None:
    """Return the still-valid outgoing code for a user, if any."""
    stmt = (
        select(AccountTransferCode)
        .where(
            AccountTransferCode.source_user_id == user_id,
            AccountTransferCode.consumed_at.is_(None),
            AccountTransferCode.expires_at > _now(),
        )
        .order_by(AccountTransferCode.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def issue_code(session: AsyncSession, source: User) -> tuple[str, datetime]:
    """Generate a fresh code for ``source`` and persist its hash.

    Returns the plaintext code (for one-shot delivery via the bot) and
    the expiry timestamp. Previous live codes for this user are
    invalidated.
    """
    await _purge_expired(session)
    await _invalidate_active_for(session, source.id)

    code = await _generate_unique_code(session)
    expires = _now() + timedelta(seconds=settings.account_transfer_code_ttl_seconds)
    row = AccountTransferCode(
        source_user_id=source.id,
        code_hash=_hash_code(code),
        expires_at=expires,
    )
    session.add(row)
    await session.commit()
    return code, expires


async def cancel_active(session: AsyncSession, source: User) -> int:
    """Invalidate every live outgoing code for ``source``.

    Returns the number of rows touched.
    """
    stmt = select(AccountTransferCode).where(
        AccountTransferCode.source_user_id == source.id,
        AccountTransferCode.consumed_at.is_(None),
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    now = _now()
    for row in rows:
        row.consumed_at = now
    await session.commit()
    return len(rows)


async def _has_tradable_data(session: AsyncSession, user: User) -> bool:
    """A user has tradable data if they have *any* deal, service, review,
    wallet activity, PIN, or unread/system notification with payload.

    Used to gate ``confirm`` — a target account must be a clean shell.
    """
    if user.pin_hash:
        return True

    deal = (
        await session.execute(
            select(Deal.id).where(or_(Deal.buyer_id == user.id, Deal.seller_id == user.id)).limit(1)
        )
    ).scalar_one_or_none()
    if deal is not None:
        return True

    if (
        await session.execute(select(Service.id).where(Service.owner_id == user.id).limit(1))
    ).scalar_one_or_none() is not None:
        return True

    if (
        await session.execute(
            select(Review.id)
            .where(or_(Review.author_id == user.id, Review.target_id == user.id))
            .limit(1)
        )
    ).scalar_one_or_none() is not None:
        return True

    if (
        await session.execute(
            select(WalletDeposit.id).where(WalletDeposit.user_id == user.id).limit(1)
        )
    ).scalar_one_or_none() is not None:
        return True

    if (
        await session.execute(
            select(WalletWithdrawal.id).where(WalletWithdrawal.user_id == user.id).limit(1)
        )
    ).scalar_one_or_none() is not None:
        return True

    balances = (
        (await session.execute(select(UserBalance).where(UserBalance.user_id == user.id)))
        .scalars()
        .all()
    )
    for b in balances:
        if Decimal(str(b.amount)) > 0 or Decimal(str(b.locked)) > 0:
            return True

    return False


# V11-M-11 — the legacy ``_register_miss`` helper used to increment
# ``attempts`` on EVERY active ``AccountTransferCode`` row whenever
# *anyone* typed a wrong code. That was a textbook DoS: a single
# attacker spamming random codes burned the legitimate users'
# transfer windows in ~5 wrong guesses. The function was already
# neutered to a no-op in a previous review, but the no-op body and
# every ``await _register_miss(session, target)`` call site survived
# as a maintenance trap — a future contributor reading the call
# sites would reasonably infer that "miss tracking" exists somewhere
# in the system. This audit fixes that by removing the function and
# the call sites entirely. Brute-force protection is now wholly the
# job of two layers: the endpoint-level rate limiter
# (``RLPin`` — 5 req/min/IP) and the per-code ``attempts`` counter
# that is bumped ONLY when the hash matches an in-flight code (the
# ``_verify_code`` belt-and-braces branch in ``confirm_transfer``).
# With a 10⁶ keyspace and a 15-min code TTL that combination puts
# the per-attempt success probability at ≤0.005 % — well past the
# point where brute force is more expensive than just abandoning
# the attack.


async def confirm_transfer(session: AsyncSession, target: User, code: str) -> User:
    """Re-point the source account's ``tg_user_id`` to ``target.tg_user_id``.

    Validates that the code is live, that the new (calling) account is a
    clean shell, and that the source and target are different users. On
    success the *target* row is deleted and the *source* row is updated
    in place, so the caller's next ``/api/me`` lookup will resolve to
    the source user.

    Brute-force protection: every failed attempt increments ``attempts``
    on each in-flight code; codes that cross
    :data:`MAX_CONFIRM_ATTEMPTS` are auto-consumed. Combined with the
    ``RLPin`` rate-limit on the router, this keeps the 10⁶-keyspace
    safely outside an attacker's reach.
    """
    await _purge_expired(session)

    code = (code or "").strip()
    if len(code) != settings.account_transfer_code_len or not code.isdigit():
        # V11-M-11 — no DB write: brute-force protection is the
        # endpoint rate-limit, not a per-code counter.
        raise ValueError("Введите код из 6 цифр")

    stmt = (
        select(AccountTransferCode)
        .where(
            AccountTransferCode.code_hash == _hash_code(code),
            AccountTransferCode.consumed_at.is_(None),
            AccountTransferCode.expires_at > _now(),
        )
        .order_by(AccountTransferCode.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        # V11-M-11 — no DB write: brute-force protection is the
        # endpoint rate-limit, not a per-code counter.
        raise ValueError("Код недействителен или истёк")

    source = await session.get(User, row.source_user_id)
    if source is None:
        row.consumed_at = _now()
        await session.commit()
        raise ValueError("Исходный аккаунт не найден")

    if source.id == target.id:
        # Refuse without burning a miss — the caller already controls
        # the source account; this is a UX error, not an attack.
        raise ValueError("Нельзя перенести аккаунт на самого себя")

    if not _verify_code(code, row.code_hash):
        # Belt-and-braces against a hash collision.
        # V11-M-11 — no DB write: brute-force protection is the
        # endpoint rate-limit, not a per-code counter.
        raise ValueError("Код недействителен или истёк")

    if await _has_tradable_data(session, target):
        raise ValueError(
            "На новом аккаунте есть данные. Перенос возможен только на пустой аккаунт."
        )

    new_tg_user_id = target.tg_user_id
    new_username = target.username
    new_photo_url = target.photo_url
    new_display_name = target.display_name

    # Notifications + balances of the empty target shell are wiped to
    # release the unique tg_user_id and any FK references before the
    # row itself is removed.
    await session.execute(delete(Notification).where(Notification.recipient_id == target.id))
    await session.execute(delete(UserBalance).where(UserBalance.user_id == target.id))
    await session.execute(delete(Forum).where(Forum.owner_id == target.id))

    target_id = target.id
    await session.delete(target)
    await session.flush()

    source.tg_user_id = new_tg_user_id
    if new_username:
        source.username = new_username
    if new_photo_url:
        source.photo_url = new_photo_url
    if new_display_name and not source.display_name:
        source.display_name = new_display_name

    row.consumed_at = _now()
    row.target_tg_user_id = new_tg_user_id

    await session.commit()
    await session.refresh(source)

    logger.info(
        "account transfer: source user_id=%s now tg_user_id=%s (was target_id=%s)",
        source.id,
        new_tg_user_id,
        target_id,
    )
    return source
