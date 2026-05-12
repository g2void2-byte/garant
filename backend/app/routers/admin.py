"""Admin-only endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import admin_user
from ..database import get_session
from ..models import Deal, DealStatus, Transaction, TxType, User
from ..schemas import (
    AdminUserUpdate,
    DealOut,
    SettingsOut,
    SettingsUpdate,
    StatsOut,
    TransactionOut,
    UserOut,
)
from ..services import (
    admin_refund,
    admin_release,
    aggregate_stats,
    commission_percent,
    insurance_deposit,
    set_setting,
    welcome_message,
)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(admin_user)])


@router.get("/stats", response_model=StatsOut)
async def stats(session: AsyncSession = Depends(get_session)) -> StatsOut:
    return StatsOut(**await aggregate_stats(session))


@router.get("/settings", response_model=SettingsOut)
async def get_settings(session: AsyncSession = Depends(get_session)) -> SettingsOut:
    return SettingsOut(
        commission_percent=await commission_percent(session),
        insurance_deposit=await insurance_deposit(session),
        welcome_message=await welcome_message(session),
    )


@router.put("/settings", response_model=SettingsOut)
async def update_settings(
    body: SettingsUpdate,
    session: AsyncSession = Depends(get_session),
) -> SettingsOut:
    if body.commission_percent is not None:
        await set_setting(session, "commission_percent", str(body.commission_percent))
    if body.insurance_deposit is not None:
        await set_setting(session, "insurance_deposit", str(body.insurance_deposit))
    if body.welcome_message is not None:
        await set_setting(session, "welcome_message", body.welcome_message)
    await session.commit()
    return SettingsOut(
        commission_percent=await commission_percent(session),
        insurance_deposit=await insurance_deposit(session),
        welcome_message=await welcome_message(session),
    )


@router.get("/users", response_model=list[UserOut])
async def list_users(
    q: str = Query(default=""),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[User]:
    stmt = select(User).order_by(User.created_at.desc()).limit(limit)
    if q:
        pattern = f"%{q.lstrip('@').lower()}%"
        stmt = stmt.where(
            or_(User.username.ilike(pattern), User.first_name.ilike(pattern))
        )
    res = await session.execute(stmt)
    return list(res.scalars().all())


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: int, session: AsyncSession = Depends(get_session)) -> User:
    res = await session.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: AdminUserUpdate,
    session: AsyncSession = Depends(get_session),
) -> User:
    res = await session.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    if body.balance_delta is not None:
        user.balance = max(0.0, user.balance + body.balance_delta)
        session.add(
            Transaction(
                user_id=user.id,
                type=TxType.ADMIN_ADJUST,
                amount=body.balance_delta,
                note=body.note or "Admin balance adjust",
            )
        )
    if body.insurance_delta is not None:
        user.insurance = max(0.0, user.insurance + body.insurance_delta)
    if body.is_banned is not None:
        user.is_banned = body.is_banned
    if body.is_admin is not None:
        user.is_admin = body.is_admin
    if body.rating is not None:
        user.rating = body.rating
    await session.commit()
    await session.refresh(user)
    return user


@router.get("/deals", response_model=list[DealOut])
async def list_deals(
    status_filter: DealStatus | None = Query(default=None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[Deal]:
    stmt = select(Deal).order_by(Deal.created_at.desc()).limit(limit)
    if status_filter:
        stmt = stmt.where(Deal.status == status_filter)
    res = await session.execute(stmt)
    return list(res.scalars().unique().all())


@router.post("/deals/{deal_id}/release", response_model=DealOut)
async def force_release(deal_id: int, session: AsyncSession = Depends(get_session)) -> Deal:
    res = await session.execute(select(Deal).where(Deal.id == deal_id))
    deal = res.scalar_one_or_none()
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deal not found")
    await admin_release(session, deal)
    await session.commit()
    await session.refresh(deal)
    return deal


@router.post("/deals/{deal_id}/refund", response_model=DealOut)
async def force_refund(deal_id: int, session: AsyncSession = Depends(get_session)) -> Deal:
    res = await session.execute(select(Deal).where(Deal.id == deal_id))
    deal = res.scalar_one_or_none()
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deal not found")
    await admin_refund(session, deal)
    await session.commit()
    await session.refresh(deal)
    return deal


@router.get("/transactions", response_model=list[TransactionOut])
async def list_transactions(
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[Transaction]:
    res = await session.execute(
        select(Transaction).order_by(Transaction.created_at.desc()).limit(limit)
    )
    return list(res.scalars().all())
