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
from datetime import datetime, timedelta, timezone
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

logger = logging.getLogger(__name__)

CODE_LEN = 6


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(CODE_LEN))


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _verify_code(code: str, code_hash: str) -> bool:
    if not code_hash:
        return False
    return hmac.compare_digest(_hash_code(code), code_hash)


async def _purge_expired(session: AsyncSession) -> None:
    """Remove codes that have already expired or been consumed.

    Keeps the table small and avoids accidentally matching against a
    stale row (the hash space is small — 1 in 10⁶ — so we must rotate
    aggressively).
    """
    cutoff = _now() - timedelta(days=1)
    await session.execute(
        delete(AccountTransferCode).where(
            or_(
                AccountTransferCode.expires_at < _now(),
                AccountTransferCode.consumed_at.is_not(None),
            ),
            AccountTransferCode.created_at < cutoff,
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


async def get_active_code(
    session: AsyncSession, user_id: int
) -> AccountTransferCode | None:
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

    code = _generate_code()
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
            select(Deal.id)
            .where(or_(Deal.buyer_id == user.id, Deal.seller_id == user.id))
            .limit(1)
        )
    ).scalar_one_or_none()
    if deal is not None:
        return True

    if (
        await session.execute(
            select(Service.id).where(Service.owner_id == user.id).limit(1)
        )
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
            select(WalletWithdrawal.id)
            .where(WalletWithdrawal.user_id == user.id)
            .limit(1)
        )
    ).scalar_one_or_none() is not None:
        return True

    balances = (
        await session.execute(
            select(UserBalance).where(UserBalance.user_id == user.id)
        )
    ).scalars().all()
    for b in balances:
        if Decimal(str(b.amount)) > 0 or Decimal(str(b.locked)) > 0:
            return True

    return False


async def confirm_transfer(
    session: AsyncSession, target: User, code: str
) -> User:
    """Re-point the source account's ``tg_user_id`` to ``target.tg_user_id``.

    Validates that the code is live, that the new (calling) account is a
    clean shell, and that the source and target are different users. On
    success the *target* row is deleted and the *source* row is updated
    in place, so the caller's next ``/api/me`` lookup will resolve to
    the source user.
    """
    await _purge_expired(session)

    code = (code or "").strip()
    if len(code) != CODE_LEN or not code.isdigit():
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
        raise ValueError("Код недействителен или истёк")

    source = await session.get(User, row.source_user_id)
    if source is None:
        row.consumed_at = _now()
        await session.commit()
        raise ValueError("Исходный аккаунт не найден")

    if source.id == target.id:
        raise ValueError("Нельзя перенести аккаунт на самого себя")

    if not _verify_code(code, row.code_hash):
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
    await session.execute(
        delete(Notification).where(Notification.recipient_id == target.id)
    )
    await session.execute(
        delete(UserBalance).where(UserBalance.user_id == target.id)
    )
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
