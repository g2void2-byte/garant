"""User-facing endpoints: profile, search, balance."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import current_user
from ..config import settings as cfg
from ..database import get_session
from ..models import Transaction, User
from ..schemas import BalanceOp, SettingsOut, TransactionOut, UserOut, UserShort
from ..services import (
    commission_percent,
    deposit,
    insurance_deposit,
    lock_insurance,
    unlock_insurance,
    welcome_message,
    withdraw,
)

router = APIRouter()


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)) -> User:
    return user


@router.get("/settings", response_model=SettingsOut)
async def public_settings(session: AsyncSession = Depends(get_session)) -> SettingsOut:
    return SettingsOut(
        commission_percent=await commission_percent(session),
        insurance_deposit=await insurance_deposit(session),
        welcome_message=await welcome_message(session),
    )


@router.get("/users/search", response_model=list[UserShort])
async def search_users(
    q: str = Query(default="", min_length=0, max_length=64),
    limit: int = Query(default=20, ge=1, le=50),
    _: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[User]:
    if not q:
        # newest 20 by default so the search panel isn't empty
        res = await session.execute(select(User).order_by(User.created_at.desc()).limit(limit))
        return list(res.scalars().all())
    pattern = f"%{q.lstrip('@').lower()}%"
    stmt = (
        select(User)
        .where(
            or_(
                User.username.ilike(pattern),
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
                cast(User.tg_id, String).ilike(pattern),
            )
        )
        .limit(limit)
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())


@router.get("/users/{tg_id}", response_model=UserShort)
async def get_user(
    tg_id: int,
    _: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> User:
    res = await session.execute(select(User).where(User.tg_id == tg_id))
    user = res.scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.get("/balance/transactions", response_model=list[TransactionOut])
async def list_transactions(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(50, ge=1, le=200),
) -> list[Transaction]:
    res = await session.execute(
        select(Transaction)
        .where(Transaction.user_id == user.id)
        .order_by(Transaction.created_at.desc())
        .limit(limit)
    )
    return list(res.scalars().all())


@router.post("/balance/deposit", response_model=UserOut)
async def balance_deposit(
    body: BalanceOp,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> User:
    # NOTE: in production this would integrate with a payment provider.
    # Here we credit the balance directly so the demo is fully functional.
    await deposit(session, user, body.amount, note=body.note or "Deposit")
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/balance/withdraw", response_model=UserOut)
async def balance_withdraw(
    body: BalanceOp,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> User:
    await withdraw(session, user, body.amount, note=body.note or "Withdraw")
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/insurance/lock", response_model=UserOut)
async def insurance_lock(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> User:
    await lock_insurance(session, user)
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/insurance/unlock", response_model=UserOut)
async def insurance_unlock(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> User:
    await unlock_insurance(session, user)
    await session.commit()
    await session.refresh(user)
    return user


@router.get("/config", response_model=dict)
async def runtime_config() -> dict:
    """Public, non-secret config the frontend may want to display."""
    return {
        "bot_username": cfg.bot_username,
        "webapp_url": cfg.webapp_url,
    }
