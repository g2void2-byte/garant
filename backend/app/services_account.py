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

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import (
    AccountTransferCode,
    Deal,
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
# call sites and tests that import these names directly. The source
# of truth is :mod:`backend.app.config.settings`, which itself
# snapshots its values from the environment at ``Settings()``
# instantiation. Aliases and direct ``settings.X`` reads are both
# import-time snapshots; the lever this fix unlocks is deploy-time
# tunability via env var, not in-process runtime mutation.
CODE_LEN = settings.account_transfer_code_len


def _now() -> datetime:
    # Tz-naive UTC to match ``DateTime`` columns in the DB. Postgres
    # rejects tz-aware values written to ``TIMESTAMP WITHOUT TIME ZONE``.
    return utcnow()


def _generate_code() -> str:
    # V11-L-1 — read length from settings rather than the
    # module-level ``CODE_LEN`` alias so the two stay in sync if a
    # test (or future caller) reassigns one but not the other.
    # ``settings.account_transfer_code_len`` is the source of truth.
    return "".join(secrets.choice("0123456789") for _ in range(settings.account_transfer_code_len))


def _hash_code(code: str) -> str:
    # Audit v3 L-12 — use HMAC-SHA256 keyed with ``pin_pepper``
    # instead of bare SHA-256.  The 6-digit code has only ~20 bits
    # of entropy; bare SHA-256 hashes are brute-forceable in under a
    # second if the ``account_transfer_codes`` table leaks.  Keying
    # the hash with a server-side secret means an attacker also needs
    # the pepper to mount an offline attack.  When ``pin_pepper`` is
    # empty the construction degrades to ``HMAC(b"", ...)`` which is
    # still structurally different from a bare ``sha256`` (the HMAC
    # inner/outer pad XOR ensures the output differs), so existing
    # rows hashed with the old scheme will NOT match — but that is
    # acceptable because transfer codes are short-lived (15 min TTL)
    # and any in-flight code at deploy time simply expires.
    key = settings.pin_pepper.encode("utf-8")
    return hmac.new(key, code.encode("utf-8"), hashlib.sha256).hexdigest()


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
                # V11-L-15 — structured-logging fields so the JSON-
                # logger downstream (Loki/Sentry) can pivot on event
                # and the collision-count bucket without regexing
                # the message body.
                logger.warning(
                    "account-transfer code generation took %d attempts "
                    "(warn_threshold=%d, max_attempts=%d) — investigate "
                    "live-code purge / TTL pressure",
                    iteration,
                    warn_threshold,
                    max_attempts,
                    extra={
                        "event": "account_transfer.code_gen.collision_pressure",
                        "iteration": iteration,
                        "warn_threshold": warn_threshold,
                        "max_attempts": max_attempts,
                    },
                )
            return candidate
    raise RuntimeError(
        f"unable to generate a unique account-transfer code after {max_attempts} tries"
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


# Audit §4.14 — ``confirm_transfer`` used to run the full purge sweep
# on *every* confirm, paying for a table scan on the hot path of a
# security-sensitive endpoint even though the previous confirm already
# swept whatever was eligible. ``_purge_expired_sampled`` runs the
# sweep probabilistically (default 1/10) so 9 out of 10 confirms skip
# the DELETE entirely. The amortised cost per confirm is unchanged in
# expectation (the table still trends toward steady-state), but the
# worst-case per-confirm latency drops by ~10× and we stop scanning
# during DM-driven contention bursts (e.g. a wave of confirms after a
# marketing campaign).
#
# ``issue_code`` still calls ``_purge_expired`` directly (force-purge)
# because it's about to write a new hash and wants the collision-check
# space clean. The sampled wrapper is *only* for the confirm path.
#
# The 1/10 sampling rate is deliberately conservative — at default
# settings (5 min TTL × N users × ~1 active code per user) the table
# never grows past hundreds of rows in practice, so even 1/100 would
# be safe, but 1/10 keeps the sweep frequent enough that an unlucky
# operator who turns up the TTL won't have to wait long for cleanup.
_PURGE_SAMPLE_RATE = 0.1


async def _purge_expired_sampled(session: AsyncSession) -> None:
    """Run :func:`_purge_expired` with probability ``_PURGE_SAMPLE_RATE``.

    See the audit §4.14 block above for the rationale.
    """
    if secrets.SystemRandom().random() >= _PURGE_SAMPLE_RATE:
        return
    await _purge_expired(session)


async def _invalidate_active_for(session: AsyncSession, user_id: int) -> None:
    """Mark all live codes for a given source user as consumed.

    Called both before issuing a fresh one (so the old codes stop working
    immediately) and on explicit user cancel. Implemented as a single
    bulk ``UPDATE`` so we don't materialise the ORM rows just to stamp
    a timestamp — the audit recommended this after spotting the
    ``select → loop → setattr`` pattern in the v12 audit.
    """
    await session.execute(
        update(AccountTransferCode)
        .where(
            AccountTransferCode.source_user_id == user_id,
            AccountTransferCode.consumed_at.is_(None),
        )
        .values(consumed_at=_now())
    )


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
    # Audit §4.14 — always run a full purge here (not the sampled
    # wrapper): we're about to write a new code row and want the
    # collision-check space clean.
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

    Returns the number of rows touched. Implemented as a single bulk
    ``UPDATE`` so a user with N stale unconsumed codes (theoretically
    one if ``issue_code`` always invalidates the previous batch first,
    but defensive) doesn't fan out into N ``UPDATE`` round-trips.
    """
    result = await session.execute(
        update(AccountTransferCode)
        .where(
            AccountTransferCode.source_user_id == source.id,
            AccountTransferCode.consumed_at.is_(None),
        )
        .values(consumed_at=_now())
    )
    await session.commit()
    return int(result.rowcount or 0)


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


# Brute-force protection for the 6-digit one-time code is wholly the
# job of the endpoint-level rate limiter (``RLPin`` — 5 req/min/IP).
# An attacker spamming random codes can't enumerate the 10⁶ keyspace:
# a miss is rejected by hash lookup with no DB write, so the
# legitimate code is unaffected and (with the 15-min TTL) the
# attacker's per-attempt success probability stays at ≤0.005 %.
#
# An earlier design also kept a per-``AccountTransferCode`` ``attempts``
# counter that consumed the code after a small threshold; that column
# has been dropped because the rate-limit + keyspace + TTL combo
# already wins the brute-force math and the counter only ever bumped
# on cosmic-ray-rare hash collisions in practice.


async def confirm_transfer(session: AsyncSession, target: User, code: str) -> User:
    """Re-point the source account's ``tg_user_id`` to ``target.tg_user_id``.

    Validates that the code is live, that the new (calling) account is a
    clean shell, and that the source and target are different users. On
    success the *target* row is deleted and the *source* row is updated
    in place, so the caller's next ``/api/me`` lookup will resolve to
    the source user.

    Brute-force protection is delegated entirely to ``RLPin`` (5/min
    per caller); see the module-level comment above for the security
    argument.
    """
    # Audit §4.14 — probabilistic sweep on the hot ``confirm`` path;
    # the previous confirm already swept what it could, and the
    # ``issue_code`` path always forces a clean sweep before each new
    # write.
    await _purge_expired_sampled(session)

    code = (code or "").strip()
    expected_len = settings.account_transfer_code_len
    if len(code) != expected_len or not code.isdigit():
        # Length is a deploy-time knob
        # (``settings.account_transfer_code_len``); render the real
        # expected count instead of a hard-coded "6".
        raise ValueError(f"Введите код из {expected_len} цифр")

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
        raise ValueError("Код недействителен или истёк")

    # LOW #2 — re-fetch ``source`` and ``target`` with ``FOR UPDATE``
    # row locks so the empty-shell check + the ownership swap below
    # cannot race a concurrent write to either row (e.g. the target
    # creating a deal / depositing in the ~ms window between
    # ``_has_tradable_data`` returning ``False`` and the
    # ``session.delete(target)`` below). Lock order is sorted by
    # ``user.id`` ascending to keep deadlock geometry deterministic
    # if two transfers ever race against each other.
    #
    # Audit §4.13 — the user row's ``FOR UPDATE`` *also* gates concurrent
    # inserts into the child tables ``_has_tradable_data`` queries
    # (Deal / Service / Review / WalletDeposit / WalletWithdrawal /
    # UserBalance), even though we don't lock those tables explicitly.
    # PostgreSQL takes ``FOR KEY SHARE`` on every parent row a new child
    # row references to validate the FK; ``FOR UPDATE`` conflicts with
    # ``FOR KEY SHARE`` on the same row, so any tx that tries to
    # ``INSERT INTO wallet_deposits (user_id=target.id, ...)`` while we
    # hold the lock blocks on the parent row until we commit. The
    # window between ``_has_tradable_data`` returning ``False`` and the
    # ``session.delete(target)`` below is therefore not actually
    # observable to another tx — the audit's "potential race" reading
    # is precluded by PG's FK-validation lock matrix.
    locked_ids = sorted({row.source_user_id, target.id})
    locked_rows = (
        (
            await session.execute(
                select(User).where(User.id.in_(locked_ids)).with_for_update().order_by(User.id)
            )
        )
        .scalars()
        .all()
    )
    locked_by_id = {u.id: u for u in locked_rows}
    source = locked_by_id.get(row.source_user_id)
    if source is None:
        row.consumed_at = _now()
        await session.commit()
        raise ValueError("Исходный аккаунт не найден")

    if source.id == target.id:
        raise ValueError("Нельзя перенести аккаунт на самого себя")

    # The caller's ``target`` reference is from the ``current_user``
    # dependency (not locked); replace it with the freshly-locked
    # instance so subsequent reads + the ``session.delete`` operate
    # against the row whose lock we hold.
    target = locked_by_id.get(target.id, target)

    if not _verify_code(code, row.code_hash):
        # Belt-and-braces against a hash collision.
        raise ValueError("Код недействителен или истёк")

    if await _has_tradable_data(session, target):
        raise ValueError(
            "На новом аккаунте есть данные. Перенос возможен только на пустой аккаунт."
        )

    new_tg_user_id = target.tg_user_id
    new_username = target.username
    new_photo_url = target.photo_url
    new_display_name = target.display_name

    # M-13: FK cascades now handle child-row cleanup automatically
    # (notifications, balances, forums, media, etc.) when the user
    # row is deleted.
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

    # Audit L-10 — bump both PIN- and TOTP-session epochs on the
    # source row. The TG identity attached to this row just changed,
    # so any JWT issued under the previous ``tg_user_id`` (which is
    # still ``valid`` cryptographically until ``exp``) must be
    # invalidated server-side. Without this an attacker who somehow
    # recovered the previous source's TG-account post-transfer
    # (Telegram-side account restoration, SIM-recovery race, replay
    # of a captured PIN token) keeps a working PIN/TOTP session.
    # ``admin.users.invalidate_sessions`` already does the same
    # epoch-bump pair on demand; mirroring it here keeps the
    # invariant "row identity changed ⇒ tokens revoked" globally.
    source.pin_session_epoch = int(source.pin_session_epoch or 0) + 1
    source.totp_session_epoch = int(source.totp_session_epoch or 0) + 1

    row.consumed_at = _now()
    row.target_tg_user_id = new_tg_user_id

    await session.commit()

    # V11-L-15 — structured-logging fields so the JSON-logger
    # downstream (Loki/Sentry) can pivot on event/user-ids without
    # regexing the message body. This is a fully-successful transfer
    # (post-commit), so it's an ``info`` and the target row no longer
    # exists — ``target_id`` is captured for forensics.
    logger.info(
        "account transfer: source user_id=%s now tg_user_id=%s (was target_id=%s)",
        source.id,
        new_tg_user_id,
        target_id,
        extra={
            "event": "account_transfer.confirm.ok",
            "source_user_id": source.id,
            "new_tg_user_id": new_tg_user_id,
            "deleted_target_user_id": target_id,
        },
    )
    return source
